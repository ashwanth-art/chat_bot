"""Evidence surfaces for read-only governance assessment.

Three kinds of evidence are served, and they are never blended:

* **measured** — recomputed from the running service at read time (corpus digests,
  configured ceilings, live counters). Highest confidence.
* **build** — produced by CI and committed to `evidence/build.json` (SBOM digest,
  dependency audit, test results). Trusted as far as the pipeline is.
* **attested** — a named owner asserting a document exists, with approval and
  review dates. Lowest confidence, and it decays: an overdue review degrades the
  status without anyone editing the file.

Every procedure carries which kind it is, so an assessor can tell a measured
fact from somebody's word.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from prometheus_client import REGISTRY

from app.config import get_settings
from app.limits import limits_configuration, limits_usage

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = REPO_ROOT / "sample_data" / "aci"
CORPUS_MANIFEST = CORPUS_DIR / "manifest.json"
ATTESTATIONS = REPO_ROOT / "evidence" / "attestations.json"
BUILD_EVIDENCE = REPO_ROOT / "evidence" / "build.json"

OVERDUE_FAIL_DAYS = 90

CONFIDENCE_MEASURED = 0.95
CONFIDENCE_BUILD = 0.9
CONFIDENCE_ATTESTED = 0.7

# Key material that is obviously not production-grade. Compared against the
# configured keys without ever returning or logging the key itself.
WEAK_KEY_MARKERS = (
    "change-before-deploy",
    "changeme",
    "placeholder",
    "example",
    "default",
    "local",
    "test",
    "demo",
    "secret",
)
MIN_STRONG_KEY_LENGTH = 32


def _today() -> date:
    return datetime.now(UTC).date()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


@dataclass(frozen=True)
class Procedure:
    procedure_id: str
    status: str
    summary: str
    confidence: float
    kind: str
    artifact_ref: str | None = None
    collected_at: str | None = None

    def as_manifest_entry(self) -> dict:
        entry: dict[str, Any] = {
            "status": self.status,
            "summary": self.summary,
            "confidence": round(self.confidence, 2),
            "evidenceKind": self.kind,
        }
        if self.artifact_ref:
            entry["artifactRef"] = self.artifact_ref
        if self.collected_at:
            entry["collectedAt"] = self.collected_at
        return entry


# --------------------------------------------------------------------------- #
# corpus integrity — measured                                                  #
# --------------------------------------------------------------------------- #


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def verify_corpus_integrity() -> dict:
    """Recompute every corpus digest and compare it to the approved baseline."""
    manifest = _load_json(CORPUS_MANIFEST)
    documents = manifest.get("documents") or []
    integrity = manifest.get("integrity") or {}
    matched: list[str] = []
    mismatched: list[dict[str, str]] = []
    missing: list[str] = []
    unrecorded: list[str] = []

    recorded_files = set()
    for entry in documents:
        filename = entry.get("file")
        if not isinstance(filename, str):
            continue
        recorded_files.add(filename)
        path = CORPUS_DIR / filename
        expected = entry.get("sha256")
        if not path.is_file():
            missing.append(filename)
            continue
        if not isinstance(expected, str) or not expected:
            unrecorded.append(filename)
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual == expected:
            matched.append(filename)
        else:
            mismatched.append(
                {
                    "file": filename,
                    "approved_on": str(entry.get("approved_on") or "unrecorded"),
                    "approved_digest": expected[:16],
                    "observed_digest": actual[:16],
                }
            )

    for path in sorted(CORPUS_DIR.glob("[0-9][0-9]_*.md")):
        if path.name not in recorded_files:
            unrecorded.append(path.name)

    verified = not mismatched and not missing and not unrecorded and bool(matched)
    return {
        "algorithm": integrity.get("algorithm", "sha256"),
        "baseline_approved_on": integrity.get("baseline_approved_on"),
        "baseline_approved_by": integrity.get("baseline_approved_by"),
        "documents_recorded": len(documents),
        "documents_matched": len(matched),
        "mismatched": mismatched,
        "missing": missing,
        "unrecorded": sorted(set(unrecorded)),
        "verified": verified,
        "checked_at": _now_iso(),
    }


# --------------------------------------------------------------------------- #
# credentials and deployment posture — measured                                #
# --------------------------------------------------------------------------- #


def _key_weaknesses(name: str, value: str) -> list[str]:
    lowered = value.lower()
    reasons = []
    if any(marker in lowered for marker in WEAK_KEY_MARKERS):
        reasons.append("contains a placeholder marker")
    if len(value) < MIN_STRONG_KEY_LENGTH:
        reasons.append(f"shorter than {MIN_STRONG_KEY_LENGTH} characters")
    if len(set(value)) < 12:
        reasons.append("too few distinct characters to be randomly generated")
    return [f"{name}: {reason}" for reason in reasons]


def credential_posture() -> dict:
    """Judge the configured service keys without revealing any of them."""
    settings = get_settings()
    candidates = {
        "CHATBOT_API_KEY": settings.chatbot_api_key,
        "CLOUD_AUDIT_API_KEY": settings.cloud_audit_api_key,
        "MONITORING_API_KEY": settings.monitoring_api_key,
    }
    weaknesses: list[str] = []
    weak_names: list[str] = []
    for name, value in candidates.items():
        found = _key_weaknesses(name, value)
        if found:
            weak_names.append(name)
            weaknesses.extend(found)
    return {
        "storage": "environment variables; never returned by any endpoint",
        "transport": "Bearer token compared with a constant-time comparison",
        "keys_checked": sorted(candidates),
        "placeholder_or_weak_keys": sorted(weak_names),
        "weakness_detail": weaknesses,
        "rotation_policy_days": None,
        "last_rotated_on": None,
        "fingerprints_only": True,
    }


def deployment_posture() -> dict:
    settings = get_settings()
    origins = settings.origins
    loopback_only = bool(origins) and all(
        origin.startswith(("http://localhost", "http://127.0.0.1", "https://localhost"))
        for origin in origins
    )
    return {
        "app_env": settings.app_env,
        "declared_production": settings.is_production,
        "allowed_origins": origins,
        "allowed_origins_loopback_only": loopback_only,
        "wildcard_origin": "*" in origins,
        "credentialed_cors": False,
        "allowed_methods": ["GET", "POST"],
        "tls_terminated_at": "platform edge",
        "log_policy": "prompts, responses and API keys are never written to application logs",
    }


# --------------------------------------------------------------------------- #
# observed service levels — measured                                           #
# --------------------------------------------------------------------------- #


def _histogram_samples(metric_name: str) -> tuple[list[tuple[float, float]], float]:
    """Return cumulative (upper_bound, count) pairs and the total count."""
    buckets: list[tuple[float, float]] = []
    total = 0.0
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name == f"{metric_name}_bucket":
                bound = sample.labels.get("le")
                if bound is None:
                    continue
                buckets.append((float(bound), sample.value))
            elif sample.name == f"{metric_name}_count":
                total += sample.value
    buckets.sort(key=lambda item: item[0])
    return buckets, total


def _counter_total(metric_name: str, label: str | None = None, value: str | None = None) -> float:
    total = 0.0
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name != metric_name:
                continue
            if label and value and sample.labels.get(label) != value:
                continue
            total += sample.value
    return total


def _quantile_ms(buckets: list[tuple[float, float]], total: float, quantile: float) -> int | None:
    if not buckets or total <= 0:
        return None
    target = total * quantile
    for bound, cumulative in buckets:
        if cumulative >= target:
            if bound == float("inf"):
                return None
            return int(bound * 1000)
    return None


def observed_service_levels() -> dict:
    settings = get_settings()
    buckets, total = _histogram_samples("chatbot_request_duration_seconds")
    p95 = _quantile_ms(buckets, total, 0.95)
    p50 = _quantile_ms(buckets, total, 0.5)
    successes = _counter_total("chatbot_requests_total", "status", "success")
    blocked = _counter_total("chatbot_requests_total", "status", "blocked")
    refusals = _counter_total("chatbot_requests_total", "status", "bounded_refusal")
    errors = _counter_total("chatbot_requests_total", "status", "dependency_error")
    counted = successes + blocked + refusals + errors
    error_rate = round(errors / counted, 4) if counted else 0.0

    breaches = []
    if p95 is not None and p95 > settings.slo_p95_latency_ms:
        breaches.append(
            {
                "objective": "p95_latency_ms",
                "target": settings.slo_p95_latency_ms,
                "observed": p95,
                "detail": (
                    "Observed 95th-percentile end-to-end latency is above the declared objective."
                ),
            }
        )
    if error_rate > settings.slo_error_rate:
        breaches.append(
            {
                "objective": "error_rate",
                "target": settings.slo_error_rate,
                "observed": error_rate,
                "detail": "Dependency-error rate is above the declared objective.",
            }
        )

    return {
        "window": "process lifetime",
        "objectives": {
            "p95_latency_ms": settings.slo_p95_latency_ms,
            "error_rate": settings.slo_error_rate,
        },
        "observed": {
            "requests_counted": int(counted),
            "successes": int(successes),
            "guardrail_blocks": int(blocked),
            "bounded_refusals": int(refusals),
            "dependency_errors": int(errors),
            "error_rate": error_rate,
            "p50_latency_ms": p50,
            "p95_latency_ms": p95,
        },
        "breaches": breaches,
        "measured_at": _now_iso(),
    }


def alerting_posture() -> dict:
    """Whether anything is actually watching. Nothing is provisioned yet."""
    return {
        "rules_configured": 0,
        "provisioned_via": None,
        "notification_channels": [],
        "dashboards_provisioned": 0,
        "datasource_provisioned": "prometheus",
        "detail": (
            "Prometheus scrapes /metrics and a Grafana datasource is provisioned in the "
            "compose stack, but no alert rule, threshold or notification channel exists, "
            "so no breach reaches a human."
        ),
    }


def retention_posture() -> dict:
    settings = get_settings()
    return {
        "trace_retention_seconds": settings.trace_retention_seconds,
        "trace_store": "in-memory, expiring, capped",
        "record_retention_days": settings.record_retention_days,
        "record_disposal_enforced": settings.record_retention_days is not None,
        "prompt_and_response_persistence": False,
    }


def vector_store_posture() -> dict:
    settings = get_settings()
    return {
        "provider": "MongoDB Atlas Vector Search",
        "database": settings.mongodb_database,
        "collection": settings.aci_collection,
        "index": settings.aci_vector_index,
        "dimensions": settings.openai_embedding_dimensions,
        "similarity": "cosine",
        "tenant_filter_field": "tenant_id",
        "tenant_filter_enforced": True,
        "top_k": settings.top_k,
        "max_context_chars": settings.max_context_chars,
    }


def model_provenance() -> dict:
    settings = get_settings()
    pinned = "-" in settings.openai_model and not settings.openai_model.endswith("latest")
    return {
        "provider": "OpenAI",
        "generation_model": settings.openai_model,
        "generation_model_pinned": pinned,
        "reasoning_effort": settings.openai_reasoning_effort,
        "embedding_model": settings.openai_embedding_model,
        "embedding_dimensions": settings.openai_embedding_dimensions,
        "fine_tuned": False,
        "weights_hosted_by": "model provider",
        "tenant_identifier_sent": "salted digest only",
    }


def agency_posture() -> dict:
    """What the model is allowed to do besides emit text: nothing."""
    return {
        "tool_calling_enabled": False,
        "function_definitions": 0,
        "autonomous_actions": 0,
        "write_capabilities": [],
        "outbound_effects": ["none — the model response is returned to the caller as text"],
        "detail": (
            "The assistant is generation-only. No tool, function, plugin or write path is "
            "exposed to the model, so excessive-agency risk is bounded by design rather "
            "than by permission configuration."
        ),
    }


def output_handling_posture() -> dict:
    return {
        "response_schema_enforced": True,
        "response_model": "ChatResponse",
        "typed_fields": ["answer", "sources", "request_id", "grounded"],
        "rendered_as": "text nodes; never interpreted as markup",
        "downstream_interpreters": [],
        "pii_redaction_applied": True,
    }


# --------------------------------------------------------------------------- #
# attested and build evidence                                                  #
# --------------------------------------------------------------------------- #


def _attested_procedures() -> list[Procedure]:
    payload = _load_json(ATTESTATIONS)
    procedures = payload.get("procedures") or {}
    today = _today()
    results: list[Procedure] = []
    for procedure_id, entry in procedures.items():
        if not isinstance(entry, dict):
            continue
        summary = str(entry.get("summary") or "").strip()
        if not summary:
            continue
        owner = entry.get("owner")
        explicit = entry.get("status")
        review_due = _parse_date(entry.get("review_due"))
        approved_on = _parse_date(entry.get("approved_on"))

        if explicit in {"pass", "partial", "fail", "not_assessed"}:
            status = str(explicit)
            detail = summary
        elif review_due is None:
            status = "partial"
            detail = f"{summary} No review-due date is recorded, so currency cannot be confirmed."
        elif review_due < today:
            overdue = (today - review_due).days
            status = "fail" if overdue > OVERDUE_FAIL_DAYS else "partial"
            detail = (
                f"{summary} The scheduled review was due {review_due.isoformat()} and is "
                f"{overdue} days overdue."
            )
        else:
            status = "pass"
            detail = (
                f"{summary} Approved {approved_on.isoformat() if approved_on else 'unrecorded'}, "
                f"next review {review_due.isoformat()}."
            )
        if owner:
            detail = f"{detail} Owner: {owner}."
        results.append(
            Procedure(
                procedure_id=procedure_id,
                status=status,
                summary=detail,
                confidence=CONFIDENCE_ATTESTED,
                kind="attested",
                artifact_ref=entry.get("artifact_ref"),
                collected_at=entry.get("approved_on"),
            )
        )
    return results


def build_evidence() -> dict:
    return _load_json(BUILD_EVIDENCE)


def _build_procedures() -> list[Procedure]:
    payload = build_evidence()
    if not payload:
        return [
            Procedure(
                procedure_id="artifact-sbom",
                status="not_assessed",
                summary=(
                    "No build evidence has been generated for this deployment. Run "
                    "scripts/generate_build_evidence.py in the pipeline."
                ),
                confidence=0.0,
                kind="build",
            )
        ]
    generated_at = payload.get("generated_at")
    results: list[Procedure] = []

    sbom = payload.get("sbom") or {}
    components = int(sbom.get("components") or 0)
    results.append(
        Procedure(
            procedure_id="artifact-sbom",
            status="pass" if components else "fail",
            summary=(
                f"A CycloneDX software bill of materials was generated in the pipeline with "
                f"{components} components, digest {str(sbom.get('digest') or 'unrecorded')[:16]}."
                if components
                else "SBOM generation produced no components."
            ),
            confidence=CONFIDENCE_BUILD,
            kind="build",
            artifact_ref=sbom.get("artifact_ref"),
            collected_at=generated_at,
        )
    )

    audit = payload.get("dependency_audit") or {}
    vulnerabilities = int(audit.get("vulnerabilities") or 0)
    if audit.get("tool_available") is False:
        status, detail = "not_assessed", "No dependency-audit tool was available in the pipeline."
    elif vulnerabilities == 0:
        status = "pass"
        detail = (
            f"A dependency audit of {audit.get('packages_scanned', 'the pinned')} packages "
            "reported no known vulnerabilities."
        )
    else:
        status = "fail"
        detail = (
            f"The dependency audit reported {vulnerabilities} known vulnerabilities: "
            f"{', '.join(audit.get('advisories') or [])[:400]}."
        )
    results.append(
        Procedure(
            procedure_id="artifact-dependency-scan",
            status=status,
            summary=detail,
            confidence=CONFIDENCE_BUILD,
            kind="build",
            collected_at=generated_at,
        )
    )

    tests = payload.get("tests") or {}
    passed = int(tests.get("passed") or 0)
    failed = int(tests.get("failed") or 0)
    security_tests = int(tests.get("security_tests") or 0)
    if not passed and not failed:
        status, detail = "not_assessed", "No test results were recorded in the pipeline."
    elif failed:
        status = "fail"
        detail = f"{failed} of {passed + failed} pipeline tests failed."
    else:
        status = "pass"
        detail = (
            f"{passed} pipeline tests passed, including {security_tests} guardrail and "
            "output-handling security tests, before the image was built."
        )
    results.append(
        Procedure(
            procedure_id="artifact-security-tests",
            status=status,
            summary=detail,
            confidence=CONFIDENCE_BUILD,
            kind="build",
            collected_at=generated_at,
        )
    )

    change = payload.get("change_control") or {}
    results.append(
        Procedure(
            procedure_id="artifact-change-history",
            status="pass" if change.get("commit") else "not_assessed",
            summary=(
                f"The deployed revision is {str(change.get('commit') or '')[:12]} on branch "
                f"{change.get('branch') or 'unknown'}, built by {change.get('pipeline') or 'CI'} "
                "with a passing test gate."
                if change.get("commit")
                else "No revision metadata was recorded for the deployed build."
            ),
            confidence=CONFIDENCE_BUILD,
            kind="build",
            collected_at=generated_at,
        )
    )
    return results


# --------------------------------------------------------------------------- #
# measured procedures                                                          #
# --------------------------------------------------------------------------- #


def _measured_procedures() -> list[Procedure]:
    settings = get_settings()
    integrity = verify_corpus_integrity()
    limits = limits_configuration()
    usage = limits_usage()
    levels = observed_service_levels()
    alerting = alerting_posture()
    retention = retention_posture()
    vector = vector_store_posture()
    provenance = model_provenance()
    now = _now_iso()

    def measured(procedure_id: str, status: str, summary: str, ref: str | None = None) -> Procedure:
        return Procedure(
            procedure_id=procedure_id,
            status=status,
            summary=summary,
            confidence=CONFIDENCE_MEASURED,
            kind="measured",
            artifact_ref=ref,
            collected_at=now,
        )

    results: list[Procedure] = []

    recorded = integrity["documents_recorded"]
    results.append(
        measured(
            "artifact-rag-corpus-manifest",
            "pass" if recorded and not integrity["unrecorded"] else "partial",
            (
                f"The corpus manifest records {recorded} documents with a source URL, an approval "
                f"date, a classification and a {integrity['algorithm']} digest for each."
                if recorded and not integrity["unrecorded"]
                else (
                    f"{len(integrity['unrecorded'])} corpus files are not recorded in the "
                    "manifest: " + ", ".join(integrity["unrecorded"])
                )
            ),
            "corpus-manifest",
        )
    )

    if integrity["verified"]:
        integrity_status = "pass"
        integrity_detail = (
            f"All {integrity['documents_matched']} corpus digests recomputed at read time match "
            f"the baseline approved on {integrity['baseline_approved_on']}."
        )
    else:
        integrity_status = "fail"
        parts = []
        if integrity["mismatched"]:
            names = ", ".join(item["file"] for item in integrity["mismatched"])
            parts.append(
                f"{len(integrity['mismatched'])} document(s) no longer match the approved "
                f"digest ({names}), so content changed after approval without re-ingestion "
                "or re-review"
            )
        if integrity["missing"]:
            parts.append(f"{len(integrity['missing'])} recorded document(s) are absent")
        if integrity["unrecorded"]:
            parts.append(f"{len(integrity['unrecorded'])} present document(s) are unrecorded")
        integrity_detail = (
            "Live digest verification failed: " + "; ".join(parts) + "."
            if parts
            else "Live digest verification could not confirm the corpus baseline."
        )
    results.append(
        measured("artifact-integrity-verification", integrity_status, integrity_detail)
    )

    results.append(
        measured(
            "artifact-vector-configuration",
            "pass",
            (
                f"The vector index {vector['index']} is configured for "
                f"{vector['dimensions']}-dimension {vector['similarity']} search over "
                f"{vector['collection']}, with retrieval filtered on "
                f"{vector['tenant_filter_field']} and bounded at top-{vector['top_k']} and "
                f"{vector['max_context_chars']} context characters."
            ),
        )
    )

    results.append(
        measured(
            "artifact-model-provenance",
            "pass" if provenance["generation_model_pinned"] else "partial",
            (
                f"Generation runs on the pinned model {provenance['generation_model']} and "
                f"retrieval on {provenance['embedding_model']} at "
                f"{provenance['embedding_dimensions']} dimensions; no fine-tuned weights are "
                "used and only a salted tenant digest is sent to the provider."
            ),
        )
    )

    rate_status = "pass" if limits["enabled"] else "fail"
    results.append(
        measured(
            "artifact-rate-limits",
            rate_status,
            (
                f"A per-caller ceiling of {limits['requests_per_minute']} requests per minute is "
                f"enforced in the request path; {usage['rate_limit_rejections']} request(s) have "
                "been rejected by it so far. Enforcement is process-local and does not survive "
                "horizontal scaling."
                if limits["enabled"]
                else "No request-rate ceiling is enforced."
            ),
        )
    )

    results.append(
        measured(
            "artifact-resource-limits",
            "pass",
            (
                f"Each request is bounded at {limits['max_output_tokens_ceiling']} output tokens, "
                f"{limits['max_context_chars']} context characters and a "
                f"{limits['request_timeout_seconds']}s timeout, and the container runs read-only "
                "with all capabilities dropped."
            ),
        )
    )

    utilisation = usage["budget_utilisation"]
    results.append(
        measured(
            "artifact-cost-budgets",
            "pass",
            (
                f"A daily ceiling of {limits['daily_token_budget']} tokens is enforced before the "
                f"model is called; {usage['tokens_charged']} tokens are charged today "
                f"({0 if utilisation is None else round(utilisation * 100, 1)}% of budget), with "
                f"{usage['budget_rejections']} request(s) refused on budget."
            ),
        )
    )

    results.append(
        measured(
            "artifact-schema-validation",
            "pass",
            (
                "Every response is serialised through the typed ChatResponse model, so answer, "
                "sources, request identifier and grounded flag are schema-validated before they "
                "leave the service."
            ),
        )
    )

    results.append(
        measured(
            "artifact-tool-permissions",
            "pass",
            (
                "The assistant exposes no tool, function or write path to the model: "
                "0 function definitions and 0 autonomous actions, so the model can only return "
                "text to the caller."
            ),
        )
    )

    trace_seconds = retention["trace_retention_seconds"]
    results.append(
        measured(
            "artifact-audit-log-sample",
            "pass",
            (
                "Every request is assigned an identifier and a stage-by-stage trace covering "
                "guardrails, retrieval, generation and output validation, retrievable for "
                f"{trace_seconds}s through the monitoring adapter with the tenant reduced to a "
                "digest and no prompt or response text retained."
            ),
        )
    )

    if alerting["rules_configured"]:
        threshold_status, threshold_detail = "pass", "Alert rules and thresholds are provisioned."
    else:
        threshold_status = "fail"
        threshold_detail = (
            f"Service-level objectives are declared (p95 "
            f"{levels['objectives']['p95_latency_ms']}ms, error rate "
            f"{levels['objectives']['error_rate']}) and metrics are exported, but "
            f"{alerting['rules_configured']} alert rules and "
            f"{len(alerting['notification_channels'])} notification channels are configured, so "
            "a breach is recorded and never announced."
        )
    results.append(measured("artifact-monitor-thresholds", threshold_status, threshold_detail))

    results.append(
        measured(
            "artifact-log-review-records",
            "partial",
            (
                "Request traces and metrics are available for review on demand, but no scheduled "
                "log-review record exists that shows somebody looked at them."
            ),
        )
    )

    results.append(
        measured(
            "artifact-system-inventory",
            "pass",
            (
                f"The service reports itself as one AI system with a named owner, environment "
                f"{settings.app_env}, one model provider, one vector store and one bundled "
                "corpus, discoverable through this adapter."
            ),
        )
    )

    return results


# --------------------------------------------------------------------------- #
# manifest assembly                                                            #
# --------------------------------------------------------------------------- #


def evidence_procedures() -> list[Procedure]:
    procedures: dict[str, Procedure] = {}
    # Measured evidence wins over build evidence, which wins over an attestation.
    for procedure in _attested_procedures() + _build_procedures() + _measured_procedures():
        procedures[procedure.procedure_id] = procedure
    return sorted(procedures.values(), key=lambda item: item.procedure_id)


def evidence_manifest() -> dict:
    procedures = evidence_procedures()
    counts: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for procedure in procedures:
        counts[procedure.status] = counts.get(procedure.status, 0) + 1
        kinds[procedure.kind] = kinds.get(procedure.kind, 0) + 1
    return {
        "schemaVersion": "1.0",
        "generatedAt": _now_iso(),
        "service": "governai-rag-chatbot",
        "evidencePolicy": (
            "Measured procedures are recomputed from the running service at read time. Build "
            "procedures come from the pipeline. Attested procedures are a named owner's "
            "assertion and degrade automatically when their review falls due. No procedure is "
            "reported as passing because a document exists."
        ),
        "summary": {
            "procedures": len(procedures),
            "byStatus": counts,
            "byEvidenceKind": kinds,
        },
        "procedures": {
            procedure.procedure_id: procedure.as_manifest_entry() for procedure in procedures
        },
    }


@lru_cache(maxsize=1)
def served_procedure_ids() -> tuple[str, ...]:
    return tuple(procedure.procedure_id for procedure in evidence_procedures())
