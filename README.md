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
| Knowledge | One combined ACI services-and-industries corpus |
| Monitoring | Prometheus-compatible `/metrics` endpoint |

At startup, the backend combines the six source summaries in `sample_data/aci` into one
logical document named `aci_services_and_industries.md`. If its content or embedding
model changes, the backend automatically creates fresh embeddings and stores the chunks
in MongoDB Atlas. Users cannot upload or replace documents through the UI.

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
