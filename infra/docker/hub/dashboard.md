# rag-chatbot-dashboard

The admin dashboard for the multi-tenant RAG chatbot platform. A Next.js application where a
tenant creates chatbots, uploads documents, chooses an AI provider, styles the embeddable
widget, reads conversations, answers support tickets and manages their team.

**Source and full documentation:** https://github.com/Nuvraxis/nuvrag-platform

## Tags

| Tag | When it moves | Use it for |
|---|---|---|
| `1.2.3` | never | production — pin this |
| `1.2`, `1` | each matching release | tracking patches or minors |
| `latest` | each stable release | trying it out |

Pre-releases such as `1.2.3-rc.1` publish under that exact version only, and never move
`latest`, `1.2` or `1`.

**Run the same version as the API.** The dashboard is compiled against types generated from
the API's OpenAPI schema, so a mismatched pair can fail in ways the browser reports oddly.

## Configuration

One variable. That is the whole list.

| Variable | Default | Notes |
|---|---|---|
| `API_BASE_URL` | `http://localhost:8000` | where this container reaches the API |

It is read **server-side**, so it can be an internal address the browser could never resolve —
`http://api:8000` on a compose network, or a Kubernetes Service name. The browser never talks
to the API directly: requests go through this container, and the session lives in an
httpOnly cookie rather than in JavaScript.

Two consequences worth knowing:

- The API's `SECURITY_DASHBOARD_CORS_ORIGINS` must contain the address **users** open this
  dashboard on, for the browser calls that do cross origins.
- The API's `DASHBOARD_BASE_URL` must be that same public address, because invitation links
  are built from it.

## Image facts

- **Port:** 3000
- **User:** non-root, UID/GID `1000`
- **Build:** Next.js `output: standalone`, so the runtime image carries only the traced
  dependencies rather than the workspace
- **Base:** `node:24-alpine`

## Running it

```bash
docker run -p 3000:3000 -e API_BASE_URL=http://api:8000 \
  nuvraxis/rag-chatbot-dashboard:latest
```

A complete `docker compose` file with the API, worker, widget, Postgres and Redis is in the
[project README](https://github.com/Nuvraxis/nuvrag-platform#running-the-published-images).

## Licence and security

See the repository. Report security issues privately through GitHub rather than in a public
issue.
