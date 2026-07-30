# ACI Knowledge Chatbot

A focused RAG chatbot for ACI Infotech services and industries. The public interface is
chat-only: the knowledge documents, embedding workflow, MongoDB storage, and API
credentials remain in the backend.

## Architecture

| Capability | Component |
|---|---|
| Chat UI and API | FastAPI + HTML/CSS/JavaScript |
| Answer generation | OpenAI Responses API |
| Embeddings | OpenAI `text-embedding-3-small` |
| Vector database | MongoDB Atlas Vector Search |
| Knowledge | 13 source-attributed ACI service, industry, and case-study documents |
| Monitoring | Prometheus metrics plus protected request-correlated RAG traces |

At startup, the backend embeds each numbered source in `sample_data/aci` as an individual
document. This preserves meaningful source names in retrieval results and makes updates
idempotent: only changed sources receive fresh embeddings. The corpus includes ACI's
service and industry catalogs plus five supplied case studies. Original case-study
documents are retained in `docs/case_studies`; the retrieval-ready summaries record
source URLs, attribution, client-identity caveats, and version differences. Users cannot
upload or replace documents through the UI.

The assistant is deliberately scoped to ACI Infotech. Unsupported general-knowledge
requests receive a polite ACI-only explanation rather than a guessed answer.

## Render deployment

The repository includes `render.yaml`. Create a Render Blueprint from this repository
and supply `OPENAI_API_KEY` and `MONGODB_URI`. Render generates the assessment bearer
keys. See [docs/RENDER_DEPLOYMENT.md](docs/RENDER_DEPLOYMENT.md) for the exact deployment,
verification, and GovernAI field mapping.

Public chat:

`https://<service>.onrender.com`

Protected assessment API:

```text
POST /v1/chat
Authorization: Bearer <CHATBOT_API_KEY>
```

The browser uses `/v1/web-chat`, fixes the tenant to `aci-infotech`, and never exposes
the backend chatbot API key.

## Request-correlated assessment traces

Tier 2 assessments can retrieve a sanitized trace after each chat request:

```text
GET /api/monitoring/requests/{request_id}
Authorization: Bearer <MONITORING_API_KEY>
```

The trace reports request limits, input and scope guardrails, tenant-filtered retrieval counts
and scores, generation latency, and output-validation decisions. It does not contain raw
prompts, retrieved text, generated answers, tenant identifiers, or credentials. Traces are
memory-only, expire after one hour, and are bounded to the most recent 500 requests.

## Evidence surfaces for Tier 3 assessment

```text
GET /api/evidence/manifest
Authorization: Bearer <CLOUD_AUDIT_API_KEY>
```

Returns a GovernAI 1.0 evidence manifest — one verdict per named procedure. Each entry declares
whether it is **measured** (recomputed from the running service now), **build** (produced by the
pipeline into `evidence/build.json`), or **attested** (a named owner's assertion, which degrades
automatically once its review-due date passes). `GET /api/audit/config` carries the underlying
configuration facts, including live corpus digest verification and a self-check that reports
weak or placeholder service keys by name without ever returning key material.

See [docs/EVIDENCE.md](docs/EVIDENCE.md) for the full procedure catalogue and the list of
deliberately open items this deployment carries so an assessment demonstrates real findings.

## Request limits

Each caller is bounded to `RATE_LIMIT_REQUESTS_PER_MINUTE` requests and the deployment to
`DAILY_TOKEN_BUDGET` tokens per day, both enforced before the model is called. Enforcement is
process-local and the audit adapter reports `distributed_enforcement: false` rather than
implying a cluster-wide guarantee.

## Local Docker

```powershell
Copy-Item .env.example .env
# Set OPENAI_API_KEY, MONGODB_URI, and replace the example bearer keys.
docker compose up -d --build
```

Open `http://localhost:8000`.

## Security notes

- Never commit `.env`.
- The public web chat consumes OpenAI API usage; monitor traffic and spending.
- Restrict MongoDB Atlas network access to the deployment's outbound addresses.
- Rotate credentials that have been shared outside your secret manager.
- The chatbot answers only from retrieved ACI context and returns source-grounding data.

Licensed under MIT.
