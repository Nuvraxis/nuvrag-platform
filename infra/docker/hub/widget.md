# rag-chatbot-widget

Serves the embeddable chat widget for the multi-tenant RAG chatbot platform: a small nginx
image carrying the loader script, the chat frame and its assets. This is the origin a
customer's website loads the widget from.

**Source and full documentation:** https://github.com/Nuvraxis/nuvrag-platform

## Tags

| Tag | When it moves | Use it for |
|---|---|---|
| `1.2.3` | never | production — pin this |
| `1.2`, `1` | each matching release | tracking patches or minors |
| `latest` | each stable release | trying it out |

Pre-releases such as `1.2.3-rc.1` publish under that exact version only, and never move
`latest`, `1.2` or `1`.

## Configuration

**No environment variables.** Its one setting is a JSON file you mount, telling the widget
where the API lives:

```json
{ "apiBase": "https://api.example.com" }
```

Mount it at `/usr/share/nginx/html/widget/config.json`:

```bash
docker run -p 8080:8080 \
  -v ./widget-config.json:/usr/share/nginx/html/widget/config.json:ro \
  nuvraxis/rag-chatbot-widget:latest
```

That address is fetched by the visitor's browser, so it must be publicly reachable — not an
internal service name. Keeping it in a mounted file rather than baking it into the bundle is
what lets the API move without every customer editing their HTML.

## What a customer embeds

```html
<script src="https://widget.example.com/widget/loader.js"
        data-chatbot-key="pk_live_xxx" async></script>
```

The loader is served from `/widget/`, has a permanently stable name and a short cache, and
resolves the current content-hashed bundle from a manifest. The bundle itself is cached for a
year and verified with Subresource Integrity, so a rollout propagates immediately without
anyone changing that snippet.

The chat UI runs in a sandboxed iframe so the host page's CSS cannot reach it and it cannot
reach the host page.

## Serving it

Everything is under the `/widget/` path — the root is not a site. Requests elsewhere get a 404
by design.

The image sets permissive CORS and `Cross-Origin-Resource-Policy: cross-origin`, because the
bundle is meant to load from any customer's domain. **That is not the access control.** Which
sites may actually use a chatbot is enforced by the API against a per-chatbot allow-list; this
container is a static file server.

Put a CDN in front of it if customer sites will carry real traffic.

## Image facts

- **Port:** 8080
- **User:** non-root, UID/GID `101`
- **Health:** `GET /healthz`
- **Size:** about 17 KB gzipped in total — the loader a page includes plus the chat UI it
  pulls in — with no third-party JavaScript at all
- **Base:** `nginxinc/nginx-unprivileged:1.27-alpine`

## Licence and security

See the repository. Report security issues privately through GitHub rather than in a public
issue.
