# RAG Chatbot Platform

[![CI](https://github.com/Nuvraxis/nuvrag-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/Nuvraxis/nuvrag-platform/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/github/license/Nuvraxis/nuvrag-platform)](https://github.com/Nuvraxis/nuvrag-platform/blob/main/LICENSE.md)
[![Docker Hub](https://img.shields.io/docker/v/nuvraxis/rag-chatbot-api?label=docker&sort=semver)](https://hub.docker.com/r/nuvraxis/rag-chatbot-api)
[![Docker Pulls](https://img.shields.io/docker/pulls/nuvraxis/rag-chatbot-api)](https://hub.docker.com/r/nuvraxis/rag-chatbot-api)
![Python](https://img.shields.io/badge/python-3.14-blue)

Multi-tenant RAG platform: organisations create chatbots, upload documents, and embed a chat
widget on their own sites. FastAPI serves the API, a Celery worker handles ingestion,
pgvector stores the embeddings, and a Next.js dashboard is where tenants manage all of it.



## Stack

| Concern | Choice |
|---|---|
| API | FastAPI (async), SQLModel, Pydantic v2 settings |
| Database | PostgreSQL 17 + pgvector, HNSW index, Row-Level Security |
| Queue / cache | Celery on Redis; Redis also backs rate limiting and chatbot config caching |
| AI | Per chatbot: Azure AI Foundry, Amazon Bedrock, Anthropic or Ollama, via LangChain |
| Object storage | Local filesystem, Azure Blob or any S3-compatible store |
| Dashboard | Next.js 16 (App Router, Server Actions), shadcn/ui on Tailwind v4, in a pnpm + Turborepo workspace |
| Widget | Dependency-free JS bundle (19 KB gzipped, loader included) served by its own nginx origin |

## Running the published images

Every release publishes four images to Docker Hub. They are public, so there is no pull
secret and no login step.

| Image | Runs | Port |
|---|---|---|
| `nuvraxis/rag-chatbot-api` | the FastAPI API; also the image you run migrations with | 8000 |
| `nuvraxis/rag-chatbot-worker` | the Celery ingestion worker (no port, no inbound traffic) | — |
| `nuvraxis/rag-chatbot-dashboard` | the Next.js dashboard | 3000 |
| `nuvraxis/rag-chatbot-widget` | nginx serving the widget bundle to tenant sites | 8080 |

Tags are `1.2.3` for one release, `1.2` and `1` to follow a line, and `latest` for the newest
stable release. Pin the full version anywhere you might need to roll back; the other three
move under you. A pre-release publishes its own version but never moves `latest`.

Postgres with pgvector, and Redis, are not in these images. Bring your own — a managed
instance, or the containers in the compose file below.

### What you must set

Two values have no usable default. Generate them once and keep them:

```bash
# Encrypts the AI provider keys tenants type into the dashboard. Back it up with the database
# password: lose it and every tenant has to re-enter their keys.
docker run --rm nuvraxis/rag-chatbot-api:latest \
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Signs access and refresh tokens. Anything long and random.
openssl rand -base64 48
```

Put both in a `.env` file next to your compose file:

```dotenv
AI_CREDENTIALS_ENCRYPTION_KEY=paste-the-fernet-key
SECURITY_JWT_SECRET=paste-the-random-string
```

The widget needs one more file. The browser fetches it, so the address has to be one a
browser can reach — not a container hostname. Save it as `widget-config.json`:

```json
{ "apiBase": "http://localhost:8000" }
```

### A compose file that works

```yaml
name: rag

x-backend: &backend
  DB_CONNECTION_STRING: postgresql+asyncpg://postgres:postgres@postgres:5432/rag_db
  REDIS_URL: redis://redis:6379/0
  AI_CREDENTIALS_ENCRYPTION_KEY: ${AI_CREDENTIALS_ENCRYPTION_KEY:?generate one, see above}
  SECURITY_JWT_SECRET: ${SECURITY_JWT_SECRET:?generate one, see above}
  # Baked into invitation links and embed snippets, so these are the URLs people actually open.
  DASHBOARD_BASE_URL: http://localhost:3000
  WIDGET_CDN_BASE_URL: http://localhost:8080/widget
  SECURITY_DASHBOARD_CORS_ORIGINS: http://localhost:3000
  STORAGE_BACKEND: local
  STORAGE_LOCAL_ROOT: /var/lib/rag/uploads

services:
  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: rag_db
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d rag_db"]
      interval: 5s
      retries: 20

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 20

  # Runs to completion before the API starts, so no process ever serves an un-migrated schema.
  migrate:
    image: nuvraxis/rag-chatbot-api:1.2.3
    environment: *backend
    command: ["alembic", "upgrade", "head"]
    depends_on:
      postgres: { condition: service_healthy }
    restart: "no"

  api:
    image: nuvraxis/rag-chatbot-api:1.2.3
    environment: *backend
    ports: ["8000:8000"]
    volumes: [uploads:/var/lib/rag/uploads]
    depends_on:
      redis: { condition: service_healthy }
      migrate: { condition: service_completed_successfully }

  worker:
    image: nuvraxis/rag-chatbot-worker:1.2.3
    environment: *backend
    # The API writes the upload, the worker reads it back to parse. With STORAGE_BACKEND=local
    # that only works if both see the same directory.
    volumes: [uploads:/var/lib/rag/uploads]
    depends_on:
      redis: { condition: service_healthy }
      migrate: { condition: service_completed_successfully }

  # The scheduler behind conversation retention. Leave it out and a chatbot's retention
  # setting is accepted and never applied. One replica only — two would fire everything twice.
  beat:
    image: nuvraxis/rag-chatbot-worker:1.2.3
    environment: *backend
    command:
      ["celery", "-A", "app.worker.celery_app.celery_app", "beat", "--loglevel=INFO",
       "--schedule=/tmp/celerybeat-schedule", "--pidfile="]
    depends_on:
      redis: { condition: service_healthy }
      migrate: { condition: service_completed_successfully }

  dashboard:
    image: nuvraxis/rag-chatbot-dashboard:1.2.3
    # Server to server, over the compose network. The browser never calls the API directly,
    # which is what lets the access token stay in an httpOnly cookie.
    environment:
      API_BASE_URL: http://api:8000
    ports: ["3000:3000"]
    depends_on: [api]

  widget:
    image: nuvraxis/rag-chatbot-widget:1.2.3
    ports: ["8080:8080"]
    volumes:
      - ./widget-config.json:/usr/share/nginx/html/widget/config.json:ro

volumes:
  pgdata:
  uploads:
```

```bash
docker compose up -d
```

- Dashboard: <http://localhost:3000>
- API and docs: <http://localhost:8000/docs>
- Widget loader: <http://localhost:8080/widget/loader.js>

Sign up on the dashboard, create a chatbot, give it an AI provider on the **AI provider** tab,
then upload a document. Nothing is configured with an AI key at this level: each chatbot
carries its own, which is what lets one deployment serve tenants on different providers.

### Upgrading

Change the tag, then let the migration run to completion before the new API serves anything:

```bash
docker compose pull
docker compose up -d migrate          # blocks until the schema is current
docker compose up -d
```

Migrations move forward only. Before upgrading anything you cannot rebuild, take a database
backup — a downgrade path exists in Alembic but is not something to meet for the first time
during an incident.

### Moving off the defaults

`STORAGE_BACKEND=local` is a directory, so it only survives one API replica sharing a volume
with the worker. For anything larger, point it at S3 or Azure Blob (see the table below); the
compose stack in this repository runs MinIO for exactly that reason.

Postgres in a container with a named volume is fine for a trial and not for anything you would
miss. RLS is also inert while the application connects as the table owner, which is the
default here — see [Tenant isolation](#tenant-isolation) before putting real tenants on it.

## Configuration

Everything is read from the environment. The API and the worker take the same set; the
dashboard takes one variable; the widget takes none.

| Image | Reads |
|---|---|
| api, worker | everything in the tables below |
| dashboard | `API_BASE_URL` only |
| widget | nothing — its one setting is the mounted `config.json` |

### Required

| Variable | Notes |
|---|---|
| `AI_CREDENTIALS_ENCRYPTION_KEY` | Fernet key. **No default; the app refuses to start without it.** Encrypts tenant provider keys at rest. |
| `SECURITY_JWT_SECRET` | Signs tokens. Has a development default that must not survive into production. |
| `DB_CONNECTION_STRING` | `postgresql+asyncpg://…`. Bare `postgresql://` and `asyncpg://` are accepted and normalised. |
| `REDIS_URL` | Cache, rate limiting, Celery broker and token revocation all use it. |

### URLs the application hands out

These end up in links and snippets other people open, so they are the public addresses rather
than internal service names.

| Variable | Default | Used for |
|---|---|---|
| `DASHBOARD_BASE_URL` | `http://localhost:3000` | invitation accept links |
| `WIDGET_CDN_BASE_URL` | `http://localhost:8080/widget` | the embed snippet given to tenants |
| `SECURITY_DASHBOARD_CORS_ORIGINS` | `http://localhost:3000` | browser origins allowed to call the API; comma-separated or a JSON array |

### Storage

| Variable | Default | Notes |
|---|---|---|
| `STORAGE_BACKEND` | `local` | `local`, `s3` or `azure_blob` |
| `STORAGE_CONTAINER` | `rag-documents` | bucket or container name |
| `STORAGE_LOCAL_ROOT` | `./var/uploads` | `local` only; must be shared between API and worker |
| `STORAGE_S3_ENDPOINT_URL` | — | set for MinIO or another S3-compatible store; omit for AWS |
| `STORAGE_S3_REGION` | `us-east-1` | |
| `STORAGE_S3_ACCESS_KEY_ID`, `STORAGE_S3_SECRET_ACCESS_KEY` | — | `s3` only |
| `STORAGE_AZURE_CONNECTION_STRING` or `STORAGE_AZURE_ACCOUNT_URL` | — | `azure_blob` only |

### Database and Redis

| Variable | Default | Notes |
|---|---|---|
| `DB_PRIVILEGED_DSN` | — | table owner, used for migrations and pre-tenant lookups. Set this when the app connects as a non-owner role, which is how RLS becomes real. |
| `DB_READ_REPLICA_DSN` | — | retrieval reads from it while ingestion writes to the primary |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `5` | per process |
| `DB_STATEMENT_TIMEOUT_MS` | `15000` | |
| `DB_PGBOUNCER_TRANSACTION_MODE` | `false` | disables prepared statement caching, required behind PgBouncer in transaction mode |
| `REDIS_BROKER_URL`, `REDIS_RESULT_BACKEND_URL` | fall back to `REDIS_URL` | split Celery onto its own instance |
| `REDIS_CHATBOT_CACHE_TTL_SECONDS` | `60` | how long a widget key lookup is cached |

### Behaviour

| Variable | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `local` | `production` disables the docs endpoints |
| `PROJECT_NAME` | `RAG Chatbot Platform` | title on the API docs |
| `DOCS_ENABLED` | `true` | ignored in production |
| `SECURITY_ACCESS_TOKEN_TTL_SECONDS` | `900` | checked against the database on every request |
| `SECURITY_REFRESH_TOKEN_TTL_SECONDS` | `1209600` | |
| `SECURITY_PASSWORD_MIN_LENGTH` | `10` | |
| `SECURITY_INVITATION_TTL_SECONDS` | `604800` | |
| `AI_REQUEST_TIMEOUT_SECONDS` | `60` | any provider call during chat or ingestion |
| `AI_TEST_TIMEOUT_SECONDS` | `20` | the dashboard's "test connection" button. Raise it if you point a chatbot at a large local model. |
| `AI_EMBEDDING_BATCH_SIZE` | `100` | |
| `AI_MAX_RETRIES` | `3` | |
| `INGESTION_MAX_UPLOAD_BYTES` | `26214400` (25 MB) | |
| `INGESTION_CHUNK_SIZE_TOKENS` / `_OVERLAP_TOKENS` | `700` / `90` | |
| `INGESTION_MAX_TASK_RETRIES` | `4` | a failed ingestion job, before it is marked `failed` for good |
| `INGESTION_CLAMAV_HOST` / `_PORT` | unset / `3310` | unset disables scanning; see [Malware scanning](#malware-scanning) |
| `RETRIEVAL_TOP_K` | `5` | per-chatbot settings override this |
| `RETRIEVAL_MIN_SIMILARITY` | `0.25` | below this a chunk is not retrieved at all, which is what produces the "no grounded answer" path |
| `RETRIEVAL_HISTORY_WINDOW_MESSAGES` | `8` | prior turns sent with each question |
| `RETRIEVAL_HNSW_EF_SEARCH` | `80` | recall against latency |
| `RETENTION_ENABLED` | `true` | whether the purge is scheduled at all. *How long* anything is kept is per chatbot, in the database — see [Conversation retention](#conversation-retention) |
| `RETENTION_PURGE_HOUR_UTC` / `_MINUTE_UTC` | `3` / `30` | UTC, not cluster-local |
| `RETENTION_PURGE_BATCH_SIZE` | `500` | conversations deleted per transaction |
| `RETENTION_PURGE_MAX_BATCHES_PER_CHATBOT` | `40` | a ceiling per run, so one backlog cannot starve other tenants |
| `RATE_LIMIT_ENABLED` | `true` | |
| `RATE_LIMIT_CHATBOT_CAPACITY` / `_REFILL_PER_SECOND` | `120` / `2.0` | per chatbot |
| `RATE_LIMIT_SESSION_CAPACITY` / `_REFILL_PER_SECOND` | `20` / `0.25` | per widget session — the session id is browser-generated, so this shapes traffic rather than stopping abuse |
| `RATE_LIMIT_TICKET_IP_CAPACITY` / `_REFILL_PER_SECOND` | `3` / `0.0014` | ~5 tickets an hour from one address, per chatbot |
| `RATE_LIMIT_TICKET_CHATBOT_CAPACITY` / `_REFILL_PER_SECOND` | `30` / `0.01` | ~36 tickets an hour per chatbot, whatever the addresses |
| `SECURITY_CLIENT_IP_HEADER` | `cf-connecting-ip` | which header carries the real client address; see [spam](#keeping-spam-out-of-the-ticket-queue) |
| `OTEL_SERVICE_NAME` | `rag-api` | names the service in traces and in Postgres `application_name` |
| `OTEL_LOG_LEVEL` | `INFO` | |
| `OTEL_LOG_FORMAT` | `json` | `console` is easier to read locally |
| `OTEL_METRICS_ENABLED` | `true` | exposes `/metrics` |
| `OTEL_TRACING_ENABLED` | `false` | needs `OTEL_EXPORTER_OTLP_ENDPOINT` |

[.env.example](.env.example) carries the same list in file form, with the comments that explain
the less obvious ones.

## Running from source

```bash
cp .env.example .env          # then set AI_CREDENTIALS_ENCRYPTION_KEY
docker compose -f infra/docker/docker-compose.yml up -d
```

This builds the images from the working tree instead of pulling them, and adds MinIO so the
S3 path is exercised locally. Migrations run as their own `migrate` service before the API
starts, the same order as production.

- Dashboard: <http://localhost:3000>
- API + docs: <http://localhost:8000/docs>
- Widget origin: <http://localhost:8080/widget/loader.js>
- MinIO console: <http://localhost:9001> (`minioadmin` / `minioadmin`)

### Running the API directly

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
uv run celery -A app.worker.celery_app.celery_app worker -Q ingestion,default --loglevel=INFO

# Optional, and only needed if you are working on conversation retention. Beat is a separate
# process from the worker; without it the sweep is never enqueued.
uv run celery -A app.worker.celery_app.celery_app beat --loglevel=INFO
```

The worker picks its pool automatically: `prefork` on Linux, `threads` on Windows — Celery's
prefork pool needs `fork()` and POSIX semaphores, so on Windows its children die with
`WinError 5` before accepting a task. Pass `--pool=solo` to override for debugging.

### Running the dashboard directly

```bash
cd frontend
pnpm install
cp apps/dashboard/.env.example apps/dashboard/.env.local   # point API_BASE_URL at the API
pnpm dev
```

`API_BASE_URL` is read at runtime and never reaches the browser: the dashboard calls the API
from its own server so the access token can stay in an `httpOnly` cookie. See
[frontend/README.md](frontend/README.md) for the workspace layout and the session design.

## Using it

Everything below is available in the dashboard; the API calls are here because they are the
quickest way to check the platform end to end.

```bash
# 1. Create an organisation and its owner
curl -X POST localhost:8000/api/v1/auth/signup -H 'content-type: application/json' \
  -d '{"organization_name":"Acme","email":"you@acme.com","password":"a-long-password"}'

# 2. Create a chatbot. The slug is generated from the name ("Support" -> "support",
#    then "support-2" on the next one) and is never taken from the request.
curl -X POST localhost:8000/api/v1/chatbots -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"name":"Support","allowed_origins":["https://acme.com"]}'

# 3. Choose its AI providers. Chat and embeddings are set independently.
curl -X PUT "localhost:8000/api/v1/chatbots/$BOT_ID/ai-config" \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' -d '{
    "chat":      {"provider":"ollama","model":"llama3.1",
                  "connection":{"base_url":"http://localhost:11434"}},
    "embedding": {"provider":"ollama","model":"nomic-embed-text",
                  "connection":{"base_url":"http://localhost:11434"}}}'

# 4. Upload a document — returns 202, the worker ingests it
#    PDF, DOCX, Markdown, MDX and plain text are supported.
curl -X POST "localhost:8000/api/v1/chatbots/$BOT_ID/documents" \
  -H "authorization: Bearer $TOKEN" -F file=@handbook.pdf

# 5. Embed the widget on the tenant's site
curl "localhost:8000/api/v1/chatbots/$BOT_ID/embed-snippet" -H "authorization: Bearer $TOKEN"

# 6. Invite a colleague. The token comes back once; send them the accept_url.
curl -X POST localhost:8000/api/v1/team/invitations -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"email":"sam@acme.com","role":"admin"}'
```

The snippet is a single tag:

```html
<script src="https://cdn.example.com/widget/loader.js" data-chatbot-key="pk_live_xxx" async></script>
```

The key and nothing else. Where the API lives is read from `config.json` on the widget origin,
written at deploy time; how the widget looks comes from the chatbot's own theme, fetched at
bootstrap. Neither is in the snippet, so the API can move and the colours can change without
any tenant editing the HTML they pasted.

Appearance is edited on the chatbot's **Design** tab: seven colours, corner radius, which
side the launcher sits on, whether the palette follows the visitor's light/dark setting, and
the header and opening message. Only what has been set is stored — an unset colour keeps the
widget's own default, dark-mode switching included, which is also what makes the tab's
"Reset" meaningful. Colours are six-digit hex and nothing else; they end up in a `style`
attribute inside the frame, and the schema is checked both when it is saved and when it is
served.

### Opening the chat from your own JavaScript

A site that would rather trigger the chat from its own "Need help?" button than from the
launcher in the corner can drive the widget with `postMessage`:

```js
window.postMessage({ type: "rag-widget:open" }, "*");
window.postMessage({ type: "rag-widget:close" }, "*");
window.postMessage({ type: "rag-widget:toggle" }, "*");
```

The loader forwards these into the frame. It also announces itself once the frame is live, so
a page that needs to command the widget during load has something to wait for:

```js
window.addEventListener("message", function (event) {
  if (event.data && event.data.type === "rag-widget:ready") {
    document.getElementById("help").onclick = function () {
      window.postMessage({ type: "rag-widget:open" }, "*");
    };
  }
});
```

Most pages will not need that. A command sent after `loader.js` has run but before the frame
has finished loading is queued and applied when it is ready, so an ordinary click handler
never has to think about timing. Only a command posted *before* `loader.js` itself executes is
lost — there is no listener attached yet — and `rag-widget:ready` is the answer to that.

**Only the embedding page can do this.** The loader accepts commands solely when
`event.source === window`, and the frame accepts them solely from its own parent. Another
iframe on the page gets nothing, including one that knows the message names and reaches
through the DOM to address the widget frame directly. A paused or archived chatbot ignores all
three, so a site cannot force open a bot whose owner has taken it down.

### Pausing a chatbot

A chatbot is `active`, `paused` or `archived`. Only `active` serves anything: for the other
two every widget endpoint — bootstrap, chat and tickets alike — answers **403
`chatbot_unavailable`**, and the widget responds by **removing itself from the page**. No
launcher, and no iframe left in the tenant's DOM.

Tenants therefore do not have to touch their HTML to take a bot down. The snippet stays where
it is and starts working again the moment the status goes back to `active` — the chatbot cache
is invalidated on update, so that takes effect immediately rather than after a TTL.

The widget only does this for answers that mean it does not belong on the page:
`chatbot_unavailable`, `origin_not_allowed` and `not_found`. A 429, a 5xx or a dropped
connection leaves it alone, because tearing a widget off a tenant's live site over a blip
would be a worse failure than a launcher that is briefly unhelpful.

### Footer links

The same tab takes a **privacy policy** and a **terms** URL, shown in the widget footer above
the branding. Leave one empty and it is not rendered; set neither and the footer is exactly
what it was.

These are `privacy_url` and `terms_url` on the chatbot — **not** members of the theme, so
"Reset to the default theme" gives the colours back without taking a tenant's privacy notice
down with them. An empty string is how a link is removed; `null` means "unchanged", as it does
for every other field on that endpoint.

```bash
curl -X PATCH "$API/api/v1/chatbots/$CHATBOT_ID" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"privacy_url": "https://acme.com/privacy", "terms_url": "https://acme.com/terms"}'
```

Both must be absolute `http`/`https` URLs with a host. That is checked when saved, checked
again when served to the widget, and checked a third time by the widget itself before it sets
an `href` — the value crosses a JSONB column and a Redis cache in between, and it ends up as
a link a visitor clicks. A value that fails the second or third check costs that one footer
link rather than the chat.

The **Powered by Nuvraxis** line links to `nuvraxis.com` with the chatbot's own header as
`utm_source`, URL-encoded. Like every other link the widget renders it opens in a new tab with
`rel="noopener noreferrer nofollow"`.

## Human takeover

A visitor who needs a person can ask for one: there is a **Talk to a human** control in the
widget footer, and the same offer appears on its own when the assistant could not ground an
answer in any document. Both open a short form — email required, name and message optional,
the message pre-filled with what they just asked.

That opens a **ticket**, which wraps the conversation the visitor was already having rather
than starting a separate thread. Staff work the queue at `/tickets` in the dashboard: filter
by chatbot and status, read the transcript with its cited passages, set status, priority and
assignment, and reply. A reply is an ordinary message on the same conversation with
`role='staff'`.

**Nothing is emailed.** There is no outbound mail transport in this deployment, and the
widget's copy is worded so it never suggests otherwise — the email address is asked for so a
human can reach the visitor, and reaching out is manual, the same arrangement as invitation
links. The visitor sees the reply by reopening the widget on the same device, which is why
the widget keeps its session id once (and only once) a ticket exists.

Because that session id now replays a transcript, it is treated as a bearer capability rather
than a label: it travels as the `X-Widget-Session` **header** (never a query parameter, which
would reach ingress logs, browser history and `Referer`), and logs record a truncated digest
of it rather than the value.

## Conversation retention

Transcripts are kept **forever by default**. That is the honest default for a platform whose
operator cannot know what its tenants are obliged to keep, and it is what every chatbot
created before this feature still does.

Each chatbot can opt into deletion instead, with **Delete conversations after** on its
settings page (`retention_days` on the API). The clock runs from a conversation's **last
message**, not its first, so a thread that is still being added to never ages out mid-way.

```bash
# 30 days from last activity
curl -X PATCH "$API/api/v1/chatbots/$CHATBOT_ID" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"retention_days": 30}'

# back to keeping everything
curl -X PATCH "$API/api/v1/chatbots/$CHATBOT_ID" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"retention_days": null}'
```

`null` is the one value on that endpoint that means something rather than "leave this
alone" — without the exception, retention would be a switch you could turn on and never off.

A conversation held by an **unresolved ticket is never purged**, however old it is. Deleting
a support request out from under whoever is working it is worse than keeping it a while
longer; resolve or close the ticket and it ages out on the next sweep.

For a single erasure request there is a direct delete, which does not wait for the sweep and
does not step over an open ticket:

```bash
curl -X DELETE "$API/api/v1/chatbots/$CHATBOT_ID/conversations/$CONVERSATION_ID" \
  -H "Authorization: Bearer $TOKEN"          # 204; admin or owner
```

Either way the messages and any tickets raised from the conversation go with it, by
`ON DELETE CASCADE`.

**The sweep needs a scheduler.** It is a Celery beat job, and beat is a separate process from
the worker — the Helm chart runs it as its own one-replica Deployment (`beat.enabled`, on by
default). Two schedulers would fire every task twice, so there is deliberately no replica
count to raise. Running the worker without beat means retention settings are accepted and
never applied, which the chart warns about on install.

```bash
# alongside the worker, when running from source
uv run celery -A app.worker.celery_app.celery_app beat --loglevel=INFO
```

## Keeping spam out of the ticket queue

`POST /public/widget/tickets` is the endpoint worth abusing: it writes a row carrying an
address the caller chose and up to 4,000 characters that a human then reads.

None of the widget's other identifiers help against a script. The public key is in the
tenant's page source, `Origin` is set by browsers and a non-browser sends whatever it likes,
and **`session_id` is generated in the browser** — so the per-session bucket that limits chat
is trivially defeated by sending a fresh id each time. The chat limits therefore shape
ordinary traffic; they do not stop anything deliberate.

Opening a ticket gets **two further buckets of its own**, keyed on the client address, which a
caller cannot simply pick:

| Bucket | Default | Stops |
|---|---|---|
| per address, per chatbot | 3 burst, ~5/hour | one caller hammering the form |
| per chatbot | 30 burst, ~36/hour | a distributed attempt where every request is a new address |

Both are far tighter than the chat limits, which is the point: a visitor asks for a human once,
not once a minute, so a ceiling that would strangle chat is generous here. Chat is untouched.

### Where the client address comes from

`SECURITY_CLIENT_IP_HEADER` names the header, defaulting to `cf-connecting-ip`. The choice
matters: `X-Forwarded-For` is *appended to*, so a caller's own value sits at the front of the
list, while **Cloudflare overwrites `CF-Connecting-IP`** on every proxied request, discarding
anything the caller sent. Behind a different proxy, name that proxy's equivalent; set it empty
to use the socket address.

> **This rests on one assumption: the origin must not be reachable except through the proxy.**
> If it is, a caller can skip the proxy and set the header itself, and the per-address limit
> becomes both bypassable and a way to exhaust someone else's allowance. A Cloudflare Tunnel,
> or a firewall restricted to the proxy's address ranges, is what holds that up.

An address that cannot be determined is not waved through — those requests share a single
bucket, so presenting nothing is not a way to opt out of the limit. Addresses are never
written to logs; a truncated digest correlates a visitor's requests without recording who
they are.

### Do the cheap part at the edge too

Origin-side limits still cost a request. On Cloudflare, a Rate Limiting Rule on
`POST /public/widget/tickets` refuses the traffic before it reaches the API at all, and the
free plan includes enough for this. Cloudflare Turnstile is the next step up and the only
thing that meaningfully stops a *determined* attacker — worth noting that it is not currently
wired in, and that adding it would put a third-party script into a widget that today ships
none.

A honeypot field is deliberately **not** included. There is no HTML form on the tenant's page
for a generic spam bot to find — the form lives in a cross-origin iframe and posts JSON — so
anything reaching this endpoint was written for this API specifically, and would simply not
send the decoy.

## AI providers

Every chatbot picks its own, and one deployment serves all of them at once. There is no
provider in the environment, the images or the Helm values.

| | Chat | Embeddings | Credentials | Connection |
|---|---|---|---|---|
| `azure` | yes | yes | `api_key` | `endpoint`, optional `api_version` |
| `bedrock` | yes | yes | `access_key_id`, `secret_access_key` | `region` |
| `anthropic` | yes | **no** | `api_key` | — |
| `ollama` | yes | yes | none | `base_url` |

Chat and embeddings are chosen **independently**, because Anthropic publishes no embeddings
API — Claude can answer over vectors that Bedrock or Ollama produced. Naming it as an
embedding provider is a 422 that says why.

`POST /chatbots/{id}/ai-config/test` calls the providers with values that have not been saved
yet: one short completion, one short embedding. The embedding call is how the vector width is
discovered — measured from what comes back, never looked up from the model's name, because
the same model is served at different widths. Provider errors are classified into a fixed set
of phrases before they are returned; a raw SDK message can quote the key it just rejected.

Once a chatbot has chunks, its embedding provider and model are frozen: vectors from one model
cannot be compared against another's. Changing them is a 409 until its documents are deleted.
`document_chunk` is partitioned by vector width, so widths coexist across tenants without a
query ever comparing two of them — Postgres treats that as an error, not a poor match.

Credentials are encrypted with `AI_CREDENTIALS_ENCRYPTION_KEY` and are write-only: `GET`
reports whether one is set, never what it is. Omit `credentials` when updating to keep the
stored value; send `{}` to clear it.

`allowed_origins` lists the **sites the widget is embedded on**, not the widget's own origin.
The frame is served from the CDN, so the `Origin` on its requests identifies the CDN for every
tenant alike; the loader runs on the tenant's page and hands its origin to the frame over
`postMessage`, where the browser fills in `event.origin` and an embedding page cannot forge it.

## Layout

```
app/
  api/          routers, dependencies, error handlers, widget CORS middleware
  core/         settings, structured logging, security primitives, credential crypto
  db/           async engines, tenant-scoped sessions (RLS)
  models/       SQLModel tables
  repositories/ query objects, including the pgvector similarity search
  schemas/      request/response models
  services/     auth, chatbot, document, widget, RAG, ingestion, storage
    ai/         provider protocols, one module per provider, and the factory
                every embedding and completion goes through
  worker/       Celery app, ingestion tasks and the scheduled retention sweep
  observability/ tracing, metrics, request-context middleware
  tools/        OpenAPI export for the frontend's type generator
alembic/        migrations (extensions -> schema -> RLS -> per-chatbot AI config ->
                document_chunk partitioned by embedding width -> tickets ->
                conversation retention -> widget footer links)
frontend/       pnpm + Turborepo workspace
  apps/dashboard/  Next.js tenant dashboard
  apps/widget/     embeddable widget source and build
  packages/        api-client, types, ui, config
infra/
  docker/       API/worker/dashboard/widget images and the local compose stack
  helm/         production chart plus per-environment values
.github/workflows/  CI and release pipelines
tests/          unit tests and live-infrastructure integration tests
```

## Tenant isolation

Every tenant-owned row carries `org_id`. Application queries filter on it, and Postgres
Row-Level Security enforces it independently: `tenant_session(org_id)` sets
`app.current_org_id` for the transaction, and each policy compares `org_id` against it. An
unset variable matches nothing, so a code path that forgets tenant scoping reads zero rows
rather than another tenant's data.

`chatbot_ai_config` carries the same policy and matters most: those rows hold tenants'
provider credentials. `ticket` matters for the same reason from the other direction — those
rows hold the email addresses of a tenant's own visitors, so a leak there is a leak of
someone else's customers. `document_chunk` is partitioned, so the policy is applied to the
parent and to every partition — a partition is a table in its own right, and a role reaching
one directly would otherwise bypass the parent's.

In production, run the API as a non-owner role so RLS actually applies, and point
`DB_PRIVILEGED_DSN` at the table owner for migrations and pre-login lookups.

## Team and sessions

An organisation starts with the owner who signed it up and grows by invitation. Roles are
`owner` > `admin` > `member`; nobody can hand out more authority than they hold, an
organisation can never be left without an active owner, and you cannot demote, suspend or
remove yourself. Removing a member keeps the documents they uploaded — `uploaded_by` is
`ON DELETE SET NULL` precisely so a departure never destroys the knowledge base. The tickets
they were assigned and the replies they wrote survive the same way, via
`ticket.assigned_to` and `message.staff_user_id`.

Invitations store only a hash of their token; the plaintext is returned once, at creation.
There is no mail transport here, so the dashboard shows the accept link for you to send.

Access tokens last fifteen minutes and are checked against the database on every request, so
a suspended or removed account stops working immediately. Refresh tokens are stateless, so
signing out, changing a role or removing a member records a revocation in Redis, keyed by
token id or user, expiring with the token it invalidates.

## Malware scanning

Set `INGESTION_CLAMAV_HOST` and every upload is scanned before any extractor parses it —
`pypdf` and `python-docx` parse hostile input for a living, so they should be the last thing
to see an unscanned file. An infected document is marked `failed` with the signature name and
is never retried; a scanner that cannot be reached fails the job instead of letting the file
through. Leave the host unset and scanning is off.

```bash
docker compose -f infra/docker/docker-compose.yml --profile security up -d clamav
INGESTION_CLAMAV_HOST=clamav docker compose -f infra/docker/docker-compose.yml up -d worker
```

## Deploying

[infra/helm/rag-platform](infra/helm/rag-platform) deploys the API, worker, scheduler,
dashboard and widget origin, and runs Alembic as a `pre-upgrade` hook so no pod rolls against
an un-migrated database. Out of the box it expects an ordinary ingress controller and the public images, and
the URLs the application advertises are derived from the ingress hostnames so they cannot
drift apart. Setting `ingress.className: tailscale` switches it to the Tailscale operator's
shape instead, where each origin becomes its own tailnet device. Postgres and Redis are
deliberately not in the chart — both are managed services or dedicated hosts in every
environment it targets.

```bash
cp infra/helm/values-secrets.example.yaml infra/helm/values-secrets.yaml   # then fill it in

helm upgrade --install rag infra/helm/rag-platform \
  --namespace rag --create-namespace --set image.tag=1.4.2 \
  --values infra/helm/values-config.yaml \
  --values infra/helm/values-secrets.yaml
```

Configuration is split by whether it can be read: `values-config.yaml` carries hostnames,
image and sizing and is committed as the reviewable record; `values-secrets.yaml` carries the
DSNs and keys and is gitignored, with a committed `.example.yaml` recording the key names.
See the [chart README](infra/helm/rag-platform/README.md) for Funnel, storage and scaling.

Three workflows, split by audience:

| Workflow | Trigger | Does |
|---|---|---|
| `ci.yml` | every push and pull request | lint, migrate, test, build — publishes nothing |
| `release.yml` | push to `main` | pushes to GHCR (private) as `sha-<commit>` and `edge` |
| `publish.yaml` | a published GitHub release with a semver tag | pushes to Docker Hub (public) as `1.2.3`, `1.2`, `1`, `latest` |

CI runs `ruff check` / `ruff format --check`, `alembic upgrade head` then `alembic check`, and
the full `pytest` suite against Postgres (pgvector) and Redis service containers — the
integration tests skip themselves when those are unreachable, so running them for real is the
point. It also fails if the committed OpenAPI schema or generated TypeScript types are stale,
runs `pnpm lint` / `typecheck` / `build`, and builds all four Docker images without pushing
them.

`values-config.yaml` pins a `sha-<commit>` tag, so landing on `main` is what produces a
deployable image for this cluster. Publishing a release additionally pushes the Helm chart to
Docker Hub as an OCI artifact, with its `appVersion` set to the release so the chart resolves
to exactly the images built beside it:

```bash
helm install rag oci://registry-1.docker.io/nuvraxis/rag-platform --version 1.2.3
```

A pre-release, or a release whose "pre-release" box is ticked, publishes its version but does
not move `latest`. The `helm upgrade` deploy job is commented out, so deploying is the manual
command above.

## Development

```bash
uv run ruff check app alembic tests
uv run ruff format app alembic tests
uv run pytest tests/test_units.py          # no infrastructure needed
uv run pytest tests/                       # adds live Postgres + Redis tests
uv run alembic check                       # fails if models and migrations disagree

pnpm --dir frontend lint
pnpm --dir frontend typecheck
pnpm --dir frontend build                  # dashboard and widget bundle
```

The integration tests run against whatever `DB_CONNECTION_STRING` and `REDIS_URL` point at,
falling back to `localhost:5432` and `localhost:6379` — the ports the compose stack publishes.
They skip themselves, loudly, when neither is reachable, so a green run with no infrastructure
is not the same as a green run with it.

The AI providers are covered without any cloud account. Azure, Bedrock and Anthropic are
tested through their builders and through mocked failures; the full ingest-and-answer loop
runs against a local Ollama, which the suite discovers from `/api/tags` and skips when it is
not running. Point it elsewhere or pin the models with `RAG_TEST_OLLAMA_URL`,
`RAG_TEST_OLLAMA_CHAT_MODEL` and `RAG_TEST_OLLAMA_EMBED_MODEL`.

The dashboard's types come from the API's OpenAPI schema rather than being hand-written.
After changing a request or response model, regenerate them:

```bash
uv run python -m app.tools.export_openapi
pnpm --dir frontend --filter @rag/types generate
```
