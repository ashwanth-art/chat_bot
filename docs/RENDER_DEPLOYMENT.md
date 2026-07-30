# Render deployment and GovernAI credentials

This project includes `render.yaml`, which creates the public chatbot web service from
the repository's Dockerfile. OpenAI and MongoDB credentials are entered in Render and
are never stored in Git.

## 1. Deploy the Blueprint

1. Sign in to Render and select **New > Blueprint**.
2. Connect `https://github.com/ashwanth-art/chat_bot`.
3. Render detects `render.yaml`. Create the `governai-rag-chatbot` service.
4. When prompted, enter the secret values for `OPENAI_API_KEY` and `MONGODB_URI`.
5. In the new Render service, open **Connect > Outbound** and copy every outbound CIDR.
   Add those ranges in MongoDB Atlas under **Security > Network Access**.
6. Wait for the deploy and open the assigned `https://<service>.onrender.com` URL.
7. Confirm that `GET https://<service>.onrender.com/health` returns a healthy status.

Render automatically generates `CHATBOT_API_KEY`, `CLOUD_AUDIT_API_KEY`, and
`MONITORING_API_KEY`. In the service dashboard, open **Environment** to copy or replace
these values. Never put them in GitHub, screenshots, or assessment notes sent to
unauthorized people.

The free Render service can sleep and has limited resources. A paid instance is
recommended for reliable assessment sessions.

## 2. Confirm the backend knowledge seed

The backend automatically embeds the 13 numbered ACI sources in `sample_data/aci` with
OpenAI `text-embedding-3-small`. Each service, industry, or case-study source is stored
separately so the API returns meaningful source names. No UI upload or deployment command
is required. On the first deployment, allow a few minutes for Atlas to finish building
the `openai_vector_index` search index.

## 3. Verify the assessment endpoints

```powershell
$base="https://<service>.onrender.com"

curl.exe "$base/health"
curl.exe "$base/api/monitoring/summary" `
  -H "Authorization: Bearer <MONITORING_API_KEY>"
curl.exe "$base/api/audit/config" `
  -H "Authorization: Bearer <CLOUD_AUDIT_API_KEY>"
curl.exe -X POST "$base/v1/chat" `
  -H "Authorization: Bearer <CHATBOT_API_KEY>" `
  -H "Content-Type: application/json" `
  -d '{\"tenant_id\":\"aci-infotech\",\"messages\":[{\"role\":\"user\",\"content\":\"What AI services does ACI provide?\"}]}'
```

Expected results:

- `/health` reports MongoDB healthy and OpenAI configured.
- The monitoring and audit endpoints return HTTP 200 with the correct keys.
- `/v1/chat` and the browser UI return an answer, `grounded: true`, and ACI source chunks.
- The same endpoints return HTTP 401 when a key is missing or incorrect.

## 4. Values for the GovernAI form

### Tier 1

| GovernAI field | Value |
|---|---|
| Chatbot API endpoint | `https://<service>.onrender.com/v1/chat` |
| Chatbot API key | Render value of `CHATBOT_API_KEY` |

### Tier 2

| GovernAI field | Value |
|---|---|
| Cloud provider | `Render + MongoDB Atlas + OpenAI API` |
| Read-only cloud API key | Render value of `CLOUD_AUDIT_API_KEY` |
| Cloud audit endpoint | `https://<service>.onrender.com/api/audit/config` |
| Monitoring provider | `Prometheus-compatible application metrics` |
| Monitoring API key | Render value of `MONITORING_API_KEY` |
| Monitoring audit endpoint | `https://<service>.onrender.com/api/monitoring/summary` |
| CI/CD pipeline URL | `https://github.com/ashwanth-art/chat_bot/actions` |

Raw Prometheus metrics are available at `https://<service>.onrender.com/metrics`.
The protected monitoring summary proves the configured metrics and logging policy.
Deploying persistent Prometheus and Grafana on Render requires paid services and a disk;
use that option if the assessor requires a dashboard URL instead of the audit endpoint.

### Tier 3

| GovernAI field | Value |
|---|---|
| Source repository URL | `https://github.com/ashwanth-art/chat_bot` |
| Staging environment URL | The Render `https://<service>.onrender.com` URL |
| Model registry URL | A separately protected MLflow deployment URL |

The Docker Compose stack includes MLflow, Prometheus, and Grafana for a full private
staging environment. The single free Render Blueprint intentionally deploys only the
chatbot. Do not claim a model-registry URL until MLflow is separately deployed and
protected.

## Credential ownership

- OpenAI supplies `OPENAI_API_KEY`.
- MongoDB Atlas supplies the database user and `MONGODB_URI`.
- Render generates or stores the three assessment bearer keys.
- Render supplies the staging URL.
- GitHub supplies repository and Actions URLs.
- A separately deployed MLflow service supplies the Tier 3 model-registry URL.

Rotate any credential that has been shared in chat before using the deployment for a
real assessment.
