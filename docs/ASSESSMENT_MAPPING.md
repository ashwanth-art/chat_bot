# GovernAI assessment: values to provide

The assessment UI requires HTTPS URLs. For a real assessment, deploy this stack behind
Caddy, Traefik, or Nginx with a trusted TLS certificate and replace the example host below.
Never use production secrets in screenshots, reports, tickets, or source control.

## Tier 1 — black box

| Assessment field | This project |
|---|---|
| Chatbot API endpoint | `https://rag.example.com/v1/chat` |
| Chatbot API key | Value of `CHATBOT_API_KEY` |

Tier 1 can exercise prompt-injection, leakage, output-filtering, consistency,
hallucination, and groundedness probes. The response includes retrieval sources and a
`grounded` signal.

## Tier 2 — gray box

| Assessment field | This project |
|---|---|
| Cloud provider | `MongoDB Atlas + OpenAI API` |
| Read-only cloud API key | Value of `CLOUD_AUDIT_API_KEY` |
| Cloud audit endpoint | `https://rag.example.com/api/audit/config` |
| Monitoring provider | `Prometheus + Grafana OSS` |
| Monitoring API key | Value of `MONITORING_API_KEY` |
| Monitoring audit endpoint | `https://rag.example.com/api/monitoring/summary` |
| Correlated request trace | `https://rag.example.com/api/monitoring/requests/{request_id}` |
| CI/CD pipeline URL | URL of `.github/workflows/ci.yml` in your repository |

Both audit endpoints are read-only and require `Authorization: Bearer <key>`. Prometheus
scrapes `/metrics` only on the private observability network. Grafana is available on port
3000. Rotate the example Grafana admin password before deployment.

The monitoring summary advertises the trace endpoint. GovernAI uses the `request_id`
returned by each probe to retrieve sanitized stage timing and decisions. Raw prompts,
retrieved chunks, answers, tenant IDs, and secrets are intentionally excluded.

## Tier 3 — white box

| Assessment field | This project |
|---|---|
| Source repository URL | Your Git HTTPS repository URL |
| Staging environment URL | `https://staging-rag.example.com` |
| Model registry URL | `https://mlflow.example.com` (MLflow service, local port 5000) |

Tier 3 reviewers receive the repository, a disposable staging deployment, dependency
lock/version files, control documentation, and MLflow access. Give reviewers time-limited,
read-only credentials. Keep Prometheus and MLflow private, and restrict MongoDB Atlas
network access to approved application hosts.

## Evidence implemented

- API-key authentication with constant-time comparison.
- Tenant-filtered vector retrieval.
- Prompt-injection blocking and untrusted-context instruction.
- PII redaction on generated output.
- Source citations and grounded/ungrounded response signal.
- Backend-only bundled knowledge; no public document-upload endpoint.
- No prompt, response, or secret logging.
- Tenant-filtered MongoDB Atlas vector retrieval with TLS in transit.
- OpenAI `text-embedding-3-small` embeddings stored in MongoDB Atlas.
- Non-root, read-only, capability-dropped chatbot container.
- Health endpoint and Prometheus request/latency/guardrail/retrieval metrics.
- Reproducible CI checks, dependency versions, tests, and container build.
