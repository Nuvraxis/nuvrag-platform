# rag-platform

The Helm chart for the multi-tenant RAG chatbot platform, published as an OCI artifact. It
deploys the API, the ingestion worker, the dashboard and the widget origin, and runs the
database migration as a `pre-upgrade` hook so no pod ever rolls against an un-migrated schema.

**Source and full documentation:** https://github.com/Nuvraxis/nuvrag-platform

## Install

```bash
helm install rag oci://registry-1.docker.io/nuvraxis/rag-platform --version 1.2.3 \
  --namespace rag --create-namespace \
  --values my-values.yaml
```

The chart pins every image to its own `appVersion`, so a release installs exactly the four
images built alongside it and `helm rollback` moves the running images back with it. No pull
secret is needed — the images are public.

## What is not in it

**PostgreSQL with the `pgvector` extension, and Redis.** Both are stateful and belong to your own
infrastructure; packaging them here would invite someone to run a database as a stateless
Deployment. Point the chart at yours.

## Minimum values

```yaml
config:
  storage:
    backend: s3
    container: rag-documents

secrets:
  values:
    DB_CONNECTION_STRING: postgresql+asyncpg://rag:...@postgres:5432/rag
    REDIS_URL: redis://redis:6379/0
    SECURITY_JWT_SECRET: ...
    AI_CREDENTIALS_ENCRYPTION_KEY: ...      # Fernet key; back it up

ingress:
  className: nginx
  hosts:
    dashboard: { enabled: true, host: rag.example.com }
    api:       { enabled: true, host: rag-api.example.com }
    widget:    { enabled: true, host: rag-widget.example.com }
  tls:
    enabled: true
    secretName: rag-platform-tls
```

Three hostnames, not one: the widget is served cross-origin to customer sites on purpose, and
the dashboard's CORS origin and the embed snippet are both derived from these names, so they
cannot drift apart.

Setting `ingress.className: tailscale` switches to the Tailscale operator's shape instead,
where each origin becomes its own tailnet device.

## Two things to get right in production

- **Run the API as a non-owner PostgreSQL role.** Row-level security does not apply to a
  table's owner, so with a single-role setup the tenant isolation policies are inert and only
  application-level filtering separates tenants. Create a role for the app, grant it DML, and
  point `DB_PRIVILEGED_DSN` at the owner for migrations.
- **Back up `AI_CREDENTIALS_ENCRYPTION_KEY`** with your database password. It decrypts every
  tenant's AI provider credentials.

The chart's own README covers scaling, KEDA on queue depth, storage backends and the migration
hook: https://github.com/Nuvraxis/nuvrag-platform/tree/main/infra/helm/rag-platform
