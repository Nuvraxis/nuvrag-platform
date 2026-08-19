# Docker Hub repository descriptions

One file per published repository. These are the pages people land on when they find the
images, so they are written for someone who has never seen the project — not as a changelog
and not as a copy of the root README.

| File | Docker Hub repository |
|---|---|
| `api.md` | `nuvraxis/rag-chatbot-api` |
| `worker.md` | `nuvraxis/rag-chatbot-worker` |
| `dashboard.md` | `nuvraxis/rag-chatbot-dashboard` |
| `widget.md` | `nuvraxis/rag-chatbot-widget` |
| `chart.md` | `nuvraxis/rag-platform` (the Helm chart, an OCI artifact) |

## How these reach Docker Hub

By hand, for now. Open the repository on Docker Hub, use **Add overview** (or Settings for the
short description) and paste the matching file. "Repository overview" is Docker Hub's name for
the same field the API calls `full_description`.

`.github/workflows/docker-hub-readme.yml` automates it and is kept, but it is
`workflow_dispatch` only: the Docker Hub API rejected the write with 403 in Actions and 401
locally, and a workflow that fails on every push is worse than one nobody runs. If a
credential that can set the overview turns up, run it and delete this paragraph.

It is deliberately separate from `publish.yaml` either way: an overview belongs to the
repository rather than to a tag, so correcting one should never mean cutting a release.

Relative links do not resolve on Docker Hub — anything pointing back at this repository has to
be an absolute `https://github.com/...` URL.
