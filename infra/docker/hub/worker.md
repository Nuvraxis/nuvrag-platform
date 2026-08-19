# rag-chatbot-worker

The ingestion worker for the multi-tenant RAG chatbot platform. It takes documents uploaded
through the API, extracts their text, splits it into passages, embeds those passages and
writes the vectors — so that an upload returns immediately and the slow work happens off the
request path.

**Source and full documentation:** https://github.com/Nuvraxis/nuvrag-platform

## Tags

| Tag | When it moves | Use it for |
|---|---|---|
| `1.2.3` | never | production — pin this |
| `1.2`, `1` | each matching release | tracking patches or minors |
| `latest` | each stable release | trying it out |

Pre-releases such as `1.2.3-rc.1` publish under that exact version only, and never move
`latest`, `1.2` or `1`.

**Run the same version as the API.** This image is built directly from
[`nuvraxis/rag-chatbot-api`](https://hub.docker.com/r/nuvraxis/rag-chatbot-api) with a
different command, and the two share a database schema.

## What it needs

The same PostgreSQL + `pgvector` and Redis as the API, **the same environment**, and the
same document storage. If `STORAGE_BACKEND=local`, the API and this worker must share that
directory as a real volume — otherwise the worker cannot read what the API just wrote, and
every document fails to ingest.

It is a Celery worker: it takes jobs from Redis and needs no inbound port and no ingress.

## Configuration

Identical to the API — see
[`nuvraxis/rag-chatbot-api`](https://hub.docker.com/r/nuvraxis/rag-chatbot-api) — plus two of
its own:

| Variable | Default | Notes |
|---|---|---|
| `CELERY_QUEUES` | `ingestion,default` | `ingestion` is the slow, bursty work; `default` carries light background tasks |
| `CELERY_CONCURRENCY` | `4` | kept low on purpose: PDF parsing is CPU-bound, so scale out on queue depth rather than up on concurrency |

`AI_CREDENTIALS_ENCRYPTION_KEY` must be **the same value as the API's**. The worker decrypts
each tenant's embedding provider credentials with it; a different key means every ingestion
job fails.

Optional malware scanning: set `INGESTION_CLAMAV_HOST` and a ClamAV daemon becomes mandatory —
a scanner that cannot be reached fails the job rather than letting the file through.

## Image facts

- **Port:** none, and none needed
- **User:** non-root, UID/GID `1001`
- **Restarts:** `--max-tasks-per-child=200`, so a leaky parser cannot accumulate
- **Base:** the API image of the same version

## Scaling

Worker load is queue depth, not CPU, so a CPU-based autoscaler will scale down while a backlog
is still draining. The Helm chart at `oci://registry-1.docker.io/nuvraxis/rag-platform`
supports KEDA on Redis list length for exactly this reason.

## Licence and security

See the repository. Report security issues privately through GitHub rather than in a public
issue.
