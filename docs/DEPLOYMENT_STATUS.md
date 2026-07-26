# Deployment status and required credentials

Status checked: 2026-07-26

## Current status

This repository is not deployed. A local `.env` may be used for development, but there is
no hosted application configuration or production/staging URL.

## Secrets required when deploying

Create `.env` from `.env.example` and replace every example value.

| Variable | Purpose | Used by |
|---|---|---|
| `CHATBOT_API_KEY` | Bearer key for chat and document-ingestion APIs | `/v1/chat`, `/v1/chat/completions`, `/v1/documents` |
| `CLOUD_AUDIT_API_KEY` | Read-only assessment key for infrastructure-control evidence | `/api/audit/config` |
| `MONITORING_API_KEY` | Read-only assessment key for monitoring evidence | `/api/monitoring/summary` |
| `OPENAI_API_KEY` | OpenAI project key for response generation | OpenAI Responses API |
| `MONGODB_URI` | MongoDB Atlas SRV connection string | Document and vector storage |
| `GRAFANA_ADMIN_PASSWORD` | Initial Grafana administrator password | Grafana on port 3000 |
| `RAG_DOMAIN` | Public DNS name used by Caddy for HTTPS | Optional TLS deployment profile |

The Grafana username is `admin` unless changed in `docker-compose.yml`. Generate different
random values for all three API keys and the Grafana password. Do not commit `.env` or send
these secrets in reports.

PowerShell example for generating one random value:

```powershell
[Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLower()
```

## Required assessment values after deployment

### Tier 1

- Chatbot endpoint: `https://<RAG_DOMAIN>/v1/chat`
- Chatbot API key: value of `CHATBOT_API_KEY`

### Tier 2

- Cloud provider: `MongoDB Atlas + OpenAI API`
- Read-only cloud API key: value of `CLOUD_AUDIT_API_KEY`
- Cloud audit endpoint: `https://<RAG_DOMAIN>/api/audit/config`
- Monitoring provider: `Prometheus + Grafana OSS`
- Monitoring API key: value of `MONITORING_API_KEY`
- Monitoring endpoint: `https://<RAG_DOMAIN>/api/monitoring/summary`
- CI/CD URL: URL of `.github/workflows/ci.yml` in the hosted Git repository

### Tier 3

- Source repository URL: HTTPS URL of the hosted Git repository
- Staging environment URL: deployed HTTPS staging URL
- Model registry URL: protected MLflow URL

## Internal services

Prometheus and MLflow should be firewalled or protected by an identity-aware proxy before
internet deployment. MongoDB Atlas should use a restricted network access list and a
least-privilege database user.
