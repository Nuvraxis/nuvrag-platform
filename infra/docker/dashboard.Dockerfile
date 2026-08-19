# Tenant dashboard (Next.js). Built from the Turborepo root so the workspace packages it
# depends on resolve the same way they do locally.

FROM node:24-alpine AS base

ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    NEXT_TELEMETRY_DISABLED=1

RUN corepack enable


FROM base AS deps
WORKDIR /repo

# Only the manifests, so the install layer survives every change that is not a dependency
# change. Each workspace member needs its own file for the lockfile to validate.
COPY frontend/pnpm-workspace.yaml frontend/pnpm-lock.yaml frontend/package.json frontend/.npmrc ./
COPY frontend/apps/dashboard/package.json ./apps/dashboard/
COPY frontend/apps/widget/package.json ./apps/widget/
COPY frontend/packages/api-client/package.json ./packages/api-client/
COPY frontend/packages/config/package.json ./packages/config/
COPY frontend/packages/types/package.json ./packages/types/
COPY frontend/packages/ui/package.json ./packages/ui/

RUN --mount=type=cache,id=pnpm-store,target=/pnpm/store pnpm install --frozen-lockfile


FROM deps AS build
WORKDIR /repo
COPY frontend/ ./
RUN pnpm --filter @rag/dashboard build


FROM base AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# `output: standalone` traces the reachable files and emits a server bundle with only those
# dependencies, so the runtime image never installs the workspace at all.
COPY --from=build --chown=node:node /repo/apps/dashboard/.next/standalone ./
COPY --from=build --chown=node:node /repo/apps/dashboard/.next/static ./apps/dashboard/.next/static

# `node` numerically: a kubelet enforcing runAsNonRoot rejects a user given by name.
USER 1000:1000
EXPOSE 3000

# `/login` is public and renders without touching the API, which is what makes it usable as
# a liveness probe: the dashboard being up and the API being up are separate questions.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "apps/dashboard/server.js"]
