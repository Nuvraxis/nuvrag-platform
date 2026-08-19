# rag-chatbot-api

The HTTP API of a multi-tenant RAG chatbot platform. It serves tenant and user management,
document upload, retrieval-augmented chat over those documents, and the public endpoints an
embeddable chat widget calls from a customer's website.

**Source and full documentation:** https://github.com/Nuvraxis/nuvrag-platform

## Tags

| Tag | When it moves | Use it for |
|---|---|---|
| `1.2.3` | never | production — pin this |
| `1.2`, `1` | each matching release | tracking patches or minors |
| `latest` | each stable release | trying it out |

Pre-releases such as `1.2.3-rc.1` publish under that exact version only, and never move
`latest`, `1.2` or `1`.

## What it needs

This image is not standalone. It requires:

- **PostgreSQL with the `pgvector` extension** — `pgvector/pgvector:pg17` is what CI runs
- **Redis 7** — cache, rate limiting, Celery broker and token revocation

Neither is bundled. Both are stateful and belong to your own infrastructure.

Document ingestion is done by a separate process: see
[`nuvraxis/rag-chatbot-worker`](https://hub.docker.com/r/nuvraxis/rag-chatbot-worker).

## Two values with no usable default

```bash
# Encrypts each tenant's AI provider keys at rest. The API refuses to start without it.
docker run --rm nuvraxis/rag-chatbot-api:latest \
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Signs access tokens. Ships with a development default that must not reach production.
openssl rand -base64 48
```

**Back up `AI_CREDENTIALS_ENCRYPTION_KEY` alongside your database password.** Losing it leaves
every stored provider credential unreadable.

## Run the migrations first

The image carries Alembic. Run this once before starting the API, and again on every upgrade —
the API does not migrate on boot, deliberately, so several replicas never race each other.

```bash
docker run --rm \
  -e DB_CONNECTION_STRING=postgresql+asyncpg://rag:rag@postgres:5432/rag \
  -e AI_CREDENTIALS_ENCRYPTION_KEY=... \
  -e SECURITY_JWT_SECRET=... \
  nuvraxis/rag-chatbot-api:latest alembic upgrade head
```

## Required configuration

| Variable | Notes |
|---|---|
| `DB_CONNECTION_STRING` | `postgresql+asyncpg://…`. Bare `postgresql://` and `asyncpg://` are accepted and normalised. |
| `REDIS_URL` | e.g. `redis://redis:6379/0` |
| `AI_CREDENTIALS_ENCRYPTION_KEY` | Fernet key, generated above. No default. |
| `SECURITY_JWT_SECRET` | 32+ bytes. Has a development default that must be overridden. |

### URLs handed out to other people

These end up in links and embed snippets that other people open, so they must be the public
addresses rather than internal service names.

| Variable | Default | Used for |
|---|---|---|
| `DASHBOARD_BASE_URL` | `http://localhost:3000` | invitation accept links |
| `WIDGET_CDN_BASE_URL` | `http://localhost:8080/widget` | the embed snippet given to tenants |
| `SECURITY_DASHBOARD_CORS_ORIGINS` | `http://localhost:3000` | browser origins allowed to call the API |

### Storage

Uploaded documents go to `local`, `s3` or `azure_blob` via `STORAGE_BACKEND`. `local` is a
per-container directory, so with more than one replica — or with the worker in its own
container — it must be a shared volume. S3 (MinIO included) is the practical choice.

The full variable list is in the
[project README](https://github.com/Nuvraxis/nuvrag-platform#configuration).

## Image facts

- **Port:** 8000
- **User:** non-root, UID/GID `1001`
- **Health:** `GET /health/live` (process up), `GET /health/ready` (dependencies reachable)
- **Base:** `python:3.14-slim-bookworm`

AI providers are **not** configured here. Each tenant chooses Azure OpenAI, Bedrock, Anthropic
or Ollama in the dashboard, and those credentials are stored encrypted in the database.

## Full stack

A working `docker compose` file covering all four images plus Postgres and Redis is in the
[project README](https://github.com/Nuvraxis/nuvrag-platform#running-the-published-images), and a
Helm chart is published at `oci://registry-1.docker.io/nuvraxis/rag-platform`.

## Licence and security

See the repository. Report security issues privately through GitHub rather than in a public
issue.
