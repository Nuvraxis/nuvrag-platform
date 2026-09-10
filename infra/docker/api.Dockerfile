# Shared image for the API and the ingestion worker. Same code, different entrypoint — which
# is what keeps their dependency sets from drifting apart.

FROM python:3.14-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv


FROM base AS deps
WORKDIR /app
# Dependencies resolve from the lockfile alone, so this layer is cached until the lock changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project


FROM base AS runtime
WORKDIR /app

RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --create-home app

COPY --from=deps /opt/venv /opt/venv
COPY --chown=app:app alembic.ini ./alembic.ini
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app

# Numeric, not `app`: a kubelet enforcing runAsNonRoot cannot prove a named user is not root
# and refuses to start the container at all.
USER 1001:1001
EXPOSE 8000

# Migrations are never run here: they belong to a pre-deploy Job, so concurrent replicas
# cannot race each other applying the same revision.
#
# One worker process, not four. Each one imports the whole application — 200 MiB resident
# before it answers anything — and four of them made a pod cost 800 MiB to sit idle. Nothing
# on this path is CPU-bound: a chat turn is spent awaiting a provider, so a second process on
# the same pod buys concurrency asyncio already had. Capacity comes from `replicaCount` and
# the autoscaler, where the scheduler can see it, rather than from a number inside the image.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
