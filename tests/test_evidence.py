import json
from datetime import date, timedelta

from app import evidence
from app.config import get_settings
from app.evidence import (
    agency_posture,
    alerting_posture,
    credential_posture,
    deployment_posture,
    evidence_manifest,
    observed_service_levels,
    verify_corpus_integrity,
)

VALID_STATUSES = {"pass", "partial", "fail", "not_assessed"}


def test_manifest_matches_the_governai_1_0_schema():
    manifest = evidence_manifest()
    assert manifest["schemaVersion"] == "1.0"
    assert manifest["generatedAt"]
    assert manifest["procedures"]
    for procedure_id, entry in manifest["procedures"].items():
        assert procedure_id.startswith(("artifact-", "document-", "adapter-", "probe-"))
        assert entry["status"] in VALID_STATUSES
        assert entry["summary"].strip()
        assert 0.0 <= entry["confidence"] <= 1.0
        assert entry["evidenceKind"] in {"measured", "build", "attested"}


def test_measured_evidence_outranks_an_attestation():
    manifest = evidence_manifest()
    # The corpus manifest is recomputed, so it must never be reported as attested.
    assert manifest["procedures"]["artifact-rag-corpus-manifest"]["evidenceKind"] == "measured"
    assert manifest["procedures"]["artifact-integrity-verification"]["evidenceKind"] == "measured"


def test_attested_evidence_is_lower_confidence_than_measured():
    manifest = evidence_manifest()
    attested = [
        entry["confidence"]
        for entry in manifest["procedures"].values()
        if entry["evidenceKind"] == "attested"
    ]
    measured = [
        entry["confidence"]
        for entry in manifest["procedures"].values()
        if entry["evidenceKind"] == "measured"
    ]
    assert attested and measured
    assert max(attested) < min(measured)


def test_an_overdue_review_degrades_without_editing_the_file(tmp_path, monkeypatch):
    overdue = (date.today() - timedelta(days=200)).isoformat()
    recent = (date.today() - timedelta(days=10)).isoformat()
    future = (date.today() + timedelta(days=90)).isoformat()
    payload = {
        "procedures": {
            "document-ai-governance-policy": {
                "owner": "o",
                "summary": "current",
                "review_due": future,
            },
            "document-risk-register": {
                "owner": "o",
                "summary": "recently overdue",
                "review_due": recent,
            },
            "artifact-bias-evaluation": {
                "owner": "o",
                "summary": "long overdue",
                "review_due": overdue,
            },
            "document-system-card": {"owner": "o", "summary": "no review date recorded"},
        }
    }
    path = tmp_path / "attestations.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(evidence, "ATTESTATIONS", path)

    results = {item.procedure_id: item for item in evidence._attested_procedures()}
    assert results["document-ai-governance-policy"].status == "pass"
    assert results["document-risk-register"].status == "partial"
    assert results["artifact-bias-evaluation"].status == "fail"
    assert results["document-system-card"].status == "partial"


def test_corpus_integrity_detects_post_approval_change():
    result = verify_corpus_integrity()
    assert result["algorithm"] == "sha256"
    assert result["documents_recorded"] >= 6
    # Every recorded document is either matched or reported as changed; nothing is skipped.
    accounted = (
        result["documents_matched"]
        + len(result["mismatched"])
        + len(result["missing"])
        + len([name for name in result["unrecorded"]])
    )
    assert accounted >= result["documents_recorded"]
    if result["mismatched"]:
        assert result["verified"] is False
        for item in result["mismatched"]:
            assert item["approved_digest"] != item["observed_digest"]


def test_credential_posture_never_returns_key_material():
    posture = credential_posture()
    serialised = json.dumps(posture)
    settings_values = ["chatbot_api_key", "cloud_audit_api_key", "monitoring_api_key"]
    from app.config import get_settings

    settings = get_settings()
    for attribute in settings_values:
        secret = getattr(settings, attribute)
        assert secret not in serialised
        assert secret[:8] not in serialised
    assert posture["fingerprints_only"] is True


def test_credential_posture_flags_placeholder_keys(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("CHATBOT_API_KEY", "aci-chatbot-local-2026-change-before-deploy")
    monkeypatch.setenv("CLOUD_AUDIT_API_KEY", "0f8c31d47a9b6e25c1d3f6a8b0e4729d5c8a1f3b")
    monkeypatch.setenv("MONITORING_API_KEY", "6b2e94af07d5c81e3a9d40b7d2c65e18a4f93b07")
    get_settings.cache_clear()

    posture = credential_posture()
    assert "CHATBOT_API_KEY" in posture["placeholder_or_weak_keys"]
    assert "CLOUD_AUDIT_API_KEY" not in posture["placeholder_or_weak_keys"]
    assert "MONITORING_API_KEY" not in posture["placeholder_or_weak_keys"]
    assert any("placeholder marker" in reason for reason in posture["weakness_detail"])


def test_deployment_posture_reports_loopback_only_origins():
    posture = deployment_posture()
    assert isinstance(posture["allowed_origins"], list)
    assert isinstance(posture["allowed_origins_loopback_only"], bool)
    assert posture["credentialed_cors"] is False


def test_alerting_posture_is_read_from_the_rule_file_prometheus_loads():
    posture = alerting_posture()
    assert posture["rules_configured"] == len(posture["rules"])
    assert posture["rules_configured"] > 0, "monitoring/alert_rules.yml should be loaded"
    assert posture["provisioned_via"] == "prometheus rule_files"
    # Both declared objectives must have a rule, or the objective is decoration.
    assert {"p95_latency_ms", "error_rate"} <= set(posture["objectives_with_a_rule"])
    for rule in posture["rules"]:
        assert rule["name"]
        assert rule["expression"], "a rule with no expression evaluates nothing"
        assert rule["severity"] != "unspecified"


def test_alerting_posture_does_not_claim_a_channel_it_lacks():
    """Thresholds existing is not the same as a breach reaching a human, and the two
    are reported separately so a rule count cannot stand in for routing."""
    posture = alerting_posture()
    assert posture["notification_channels"] == []
    assert "reaches no human" in posture["detail"]


def test_alerting_posture_reports_zero_when_the_rule_file_is_unreadable(monkeypatch, tmp_path):
    """A missing or malformed file must read as no thresholds at all. Falling back to
    the last known good answer would report protection that is not running."""
    monkeypatch.setattr(evidence, "ALERT_RULES", tmp_path / "absent.yml")
    assert evidence.alerting_posture()["rules_configured"] == 0

    broken = tmp_path / "broken.yml"
    broken.write_text("groups: [ unclosed", encoding="utf-8")
    monkeypatch.setattr(evidence, "ALERT_RULES", broken)
    assert evidence.alerting_posture()["rules_configured"] == 0


def test_alert_rule_thresholds_agree_with_the_declared_objectives():
    """A rule that fires at a different number than the objective it guards is worse
    than no rule: it makes a breach invisible while looking like coverage."""
    settings = get_settings()
    rules = {rule["objective"]: rule["expression"] for rule in alerting_posture()["rules"]}

    def threshold(expression: str) -> float:
        return float(expression.rsplit(">", 1)[1].strip())

    # The latency rule works in seconds; the objective is declared in milliseconds.
    assert threshold(rules["p95_latency_ms"]) == settings.slo_p95_latency_ms / 1000
    assert threshold(rules["error_rate"]) == settings.slo_error_rate


def test_agency_posture_reports_no_tool_surface():
    posture = agency_posture()
    assert posture["tool_calling_enabled"] is False
    assert posture["function_definitions"] == 0
    assert posture["write_capabilities"] == []


def test_observed_service_levels_declare_objectives_and_breaches():
    levels = observed_service_levels()
    assert levels["objectives"]["p95_latency_ms"] > 0
    assert 0 <= levels["objectives"]["error_rate"] <= 1
    assert isinstance(levels["breaches"], list)
    for breach in levels["breaches"]:
        assert breach["objective"] in {"p95_latency_ms", "error_rate"}
        assert breach["observed"] is not None


def test_the_container_image_carries_every_directory_evidence_reads_from():
    """The manifest is read at request time, so a directory left out of the image
    silently downgrades every procedure in it to not_assessed. This caught exactly
    that: `evidence/` was absent from the image while the code read it happily in
    development."""
    dockerfile = (evidence.REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    copied = {
        line.split()[1].strip("./")
        for line in dockerfile.splitlines()
        if line.startswith("COPY ")
    }
    required = {
        path.relative_to(evidence.REPO_ROOT).parts[0]
        for path in (
            evidence.CORPUS_DIR,
            evidence.ATTESTATIONS,
            evidence.BUILD_EVIDENCE,
            evidence.ALERT_RULES,
            evidence.PROMETHEUS_CONFIG,
        )
    }
    assert required <= copied, f"not copied into the image: {sorted(required - copied)}"
