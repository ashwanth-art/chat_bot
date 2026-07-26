# GovernAI Open RAG Chatbot

A production-oriented RAG chatbot designed to supply the evidence and access expected by
the GovernAI Tier 1, Tier 2, and Tier 3 assessment. It uses the OpenAI Responses API for
answer generation, MongoDB Atlas for document and vector storage, and an open-source local
embedding model.

## Technology stack

| Capability | Component | Cost |
|---|---|---|
| API and web chat | FastAPI + plain HTML/CSS/JS | Free / OSS |
| Answer generation | OpenAI Responses API (`gpt-5.6-sol` by default) | API usage billed by OpenAI |
| Embeddings | FastEmbed ONNX + sentence-transformers MiniLM | Free / OSS |
| Document and vector database | MongoDB Atlas Vector Search | Atlas plan dependent |
| Monitoring | Prometheus + Grafana OSS | Free / OSS |
| Model registry | MLflow | Free / OSS |
| Packaging | Docker Compose | Free / OSS |

## Quick start

Prerequisites: Docker Desktop with at least 8 GB RAM available.

```powershell
Copy-Item .env.example .env
# Add OPENAI_API_KEY and MONGODB_URI, then replace all example keys.
docker compose up -d --build
```

Open:

- Chat UI and API: `http://localhost:8000`
- OpenAPI: `http://localhost:8000/docs`
- Grafana: `http://localhost:3000`
- Prometheus: `http://localhost:9090`
- MLflow registry: `http://localhost:5000`

The first document upload downloads the open-source embedding model and may take several
minutes. The application asks Atlas to create the `vector_index` search index; Atlas may
take a few minutes to finish building it before vector queries are ready.

## Load the included ACI Infotech corpus

Six concise, source-linked summaries from ACI Infotech's official website are included in
`sample_data/aci`. They cover the company overview, Applied AI & ML, Data Engineering,
Cyber Security, Healthcare, and Financial Services. The retrieval date and original URL
are recorded in each document and in `sample_data/aci/manifest.json`.

After the chatbot service is running, index all six pages:

```powershell
docker compose exec chatbot python scripts/ingest_aci_corpus.py
```

In the web interface, use tenant ID `aci-infotech`. Example questions:

- What AI and machine-learning services does ACI provide?
- How does ACI approach MLOps and AI governance?
- What data-engineering engagement phases does ACI describe?
- What healthcare interoperability capabilities are listed?
- What financial-services use cases are supported?

The corpus is a retrieval dataset based on public company claims, not an independent
validation of those claims. Re-run source review before production use because website
content can change.

For an internet-reachable staging host, set `RAG_DOMAIN` to a DNS name pointing at the
host, allow ports 80/443, and start the optional Caddy TLS profile:

```powershell
docker compose --profile tls up -d
```

Caddy obtains and renews a trusted certificate automatically. Keep ports 8000, 3000,
5000, and 9090 firewalled from the public internet in staging.

## API examples

Upload knowledge:

```powershell
curl.exe -X POST "http://localhost:8000/v1/documents?tenant_id=demo" `
  -H "Authorization: Bearer YOUR_CHATBOT_KEY" `
  -F "file=@sample_data/employee_handbook.md"
```

Ask a grounded question:

```powershell
curl.exe -X POST "http://localhost:8000/v1/chat" `
  -H "Authorization: Bearer YOUR_CHATBOT_KEY" `
  -H "Content-Type: application/json" `
  -d '{\"tenant_id\":\"demo\",\"messages\":[{\"role\":\"user\",\"content\":\"What is the support window?\"}]}'
```

Read the Tier 2 evidence endpoints:

```powershell
curl.exe "http://localhost:8000/api/audit/config" -H "Authorization: Bearer YOUR_AUDIT_KEY"
curl.exe "http://localhost:8000/api/monitoring/summary" -H "Authorization: Bearer YOUR_MONITORING_KEY"
```

## Assessment tiers

- Tier 1 (55–60%): `/v1/chat` plus `CHATBOT_API_KEY`.
- Tier 2 (80–85%): Tier 1 plus read-only audit and monitoring endpoints, Prometheus/
  Grafana, container configuration, and CI.
- Tier 3 (100% access): Tier 2 plus this source repository, a disposable TLS staging
  deployment, MongoDB corpus review, and the MLflow registry.

See [docs/ASSESSMENT_MAPPING.md](docs/ASSESSMENT_MAPPING.md) for the exact value to place
in every assessment field.

For a Render deployment, use the included `render.yaml` Blueprint and follow
[docs/RENDER_DEPLOYMENT.md](docs/RENDER_DEPLOYMENT.md). It explains where every
GovernAI credential comes from and provides verification commands.

## Security and operational notes

- Replace every example secret. Do not commit `.env`.
- Put public/staging access behind TLS and an identity-aware reverse proxy.
- Keep Prometheus, Grafana, and MLflow private.
- Restrict MongoDB Atlas network access and use a least-privilege database user.
- Rotate the supplied OpenAI and MongoDB credentials before production deployment.
- Use one tenant ID per organization and authorize tenant selection in your production
  identity layer. The demo uses an API key and caller-supplied tenant ID for clarity.
- Configure MongoDB backups and retention, back up MLflow, and test restoration.
- The included regex guardrails are a first layer, not a complete security boundary.
  Maintain an adversarial evaluation set and retest after model, prompt, or corpus changes.

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
$env:CHATBOT_API_KEY="development-chatbot-key"
$env:CLOUD_AUDIT_API_KEY="development-audit-key"
$env:MONITORING_API_KEY="development-monitor-key"
ruff check app tests
pytest -q
uvicorn app.main:app --reload
```

Licensed under MIT.
