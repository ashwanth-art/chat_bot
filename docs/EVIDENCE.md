# Evidence surfaces

This service is the assessment target for GovernAI. It exposes read-only evidence so an
external assessor can reach a verdict without a human collecting screenshots.

Three endpoints carry evidence, each behind its own bearer key:

| Endpoint | Key | What it carries |
| --- | --- | --- |
| `GET /api/audit/config` | `CLOUD_AUDIT_API_KEY` | Configuration facts: deployment, credentials posture, request limits, retention, vector store, model provenance, agency, output handling, live corpus integrity |
| `GET /api/monitoring/summary` | `MONITORING_API_KEY` | Observed service levels against declared objectives, alerting posture, live usage counters, retention |
| `GET /api/monitoring/requests/{id}` | `MONITORING_API_KEY` | Stage-by-stage trace for one request |
| `GET /api/evidence/manifest` | `CLOUD_AUDIT_API_KEY` | GovernAI 1.0 evidence manifest — one verdict per named procedure |

## The three kinds of evidence

Every procedure in the manifest declares `evidenceKind`, and the three are never blended:

- **`measured`** (confidence 0.95) — recomputed from the running service at read time. Corpus
  digests are re-hashed on every call; limits, budgets and counters are read live. If the
  service changes, the answer changes, with nobody editing a file.
- **`build`** (confidence 0.90) — produced by the pipeline into `evidence/build.json` by
  `scripts/generate_build_evidence.py`: CycloneDX SBOM, `pip-audit` results, test counts, and
  the revision being deployed. Trusted exactly as far as the pipeline is.
- **`attested`** (confidence 0.70) — a named owner asserting that a document exists, in
  `evidence/attestations.json`, with an approval date and a review-due date. **An attestation
  decays**: once `review_due` passes, the status drops to `partial`, and past 90 days overdue it
  drops to `fail`. Nobody has to remember to downgrade it.

This distinction is the point. A governance product that treats "we have a policy" and "the
digest matches" as the same fact is not measuring anything. An assessor reading this manifest
can tell which verdicts are machine facts and which are somebody's word.

## Known open items

These are real, and they are deliberately left open so the assessment demonstrates findings and
remediation rather than an all-green wall. Each one is genuinely true of this deployment — the
assessor detects them, they are not seeded into any report.

1. **Placeholder service keys.** `CHATBOT_API_KEY`, `CLOUD_AUDIT_API_KEY` and
   `MONITORING_API_KEY` are set to values containing `change-before-deploy`. The service detects
   this about itself in `credential_posture()` and reports the *names* of the weak keys — never a
   key value, not even a fingerprint of one. Fix: generate values with
   `openssl rand -hex 32` and set them in the platform environment.
2. **Loopback-only CORS on a public deployment.** `ALLOW_ORIGINS` is
   `http://localhost:8000` while the service answers on a public hostname. Fix: set the real
   front-end origin.
3. **Environment declares itself non-production.** `APP_ENV=development` on a publicly reachable
   deployment. Fix: set `APP_ENV=production`.
4. **No key rotation policy.** `rotation_policy_days` and `last_rotated_on` are null because
   neither exists. Fix: adopt a rotation interval and record the last rotation.
5. **Nothing is alerting.** Prometheus scrapes `/metrics` and a Grafana datasource is
   provisioned in the compose stack, but zero alert rules and zero notification channels exist,
   so an objective breach is recorded and never announced. Fix: provision alert rules for the
   declared p95 latency and error-rate objectives.
6. **No retention schedule.** `RECORD_RETENTION_DAYS` is unset, so stored corpus records have no
   defined disposal date. Request traces do expire, on a fixed in-memory timer.
7. **Corpus drift fixture.** `sample_data/aci/05_healthcare.md` carries a paragraph added after
   its digest was approved, so live verification reports a mismatch against
   `sample_data/aci/manifest.json`. This is the intended demonstration of
   `artifact-integrity-verification` catching post-approval change. **To clear it**, re-approve
   the content: recompute the digest and update the `sha256` and `approved_on` fields for that
   document in the manifest.
8. **Overdue reviews.** `artifact-bias-evaluation` is past 90 days overdue (`fail`) and
   `document-evaluation-methodology` is recently overdue (`partial`). Both are date arithmetic
   against `review_due`, not a hard-coded status.
9. **Untested recovery.** The disaster-recovery and backup entries are explicitly `partial`: the
   plans exist, but no restore has ever been exercised by this team.
10. **Process-local limit enforcement.** Rate limiting and the daily token budget are enforced
    in-process, which does not survive horizontal scaling. The adapter reports
    `distributed_enforcement: false` rather than implying a guarantee it cannot make.

## Regenerating build evidence

```bash
pip install -r requirements-dev.txt
python scripts/generate_build_evidence.py
```

This writes `evidence/build.json` and `evidence/sbom.cdx.json`. CI runs the same script, so a
build whose evidence was never generated reports `not_assessed` — never a pass.

## What is never exposed

No endpoint returns a key, a prompt, a response, a document body, a connection string or a
tenant identifier in the clear. Tenants appear only as a truncated salted digest. The manifest
carries verdicts and summaries, not the documents themselves.
