# rag-platform

Deploys the API, the ingestion worker, the Celery beat scheduler, the dashboard and the widget
origin, each as its own Deployment, plus the schema migration as a pre-upgrade hook.

Defaults target an ordinary cluster: the public images on Docker Hub, and a single
host-routed Ingress under whatever controller you run. This project's own cluster is the
unusual one — GHCR, the Tailscale operator, an in-cluster MinIO — and says so in
`infra/helm/values-config.yaml` rather than in the chart's defaults.

Postgres and Redis are **not** in this chart. Both are managed services or dedicated hosts in
every environment this targets, and packaging them would make it easy to accidentally run a
database as a stateless Deployment.

## Two ways to get this chart

|  | Source | Images | Who it is for |
|---|---|---|---|
| **From this checkout** | `infra/helm/rag-platform` | GHCR, private — via `values-config.yaml` | this project's own cluster, deploying a specific commit |
| **From Docker Hub** | `oci://registry-1.docker.io/nuvraxis/rag-platform` | Docker Hub, public — the chart's own defaults | anyone installing a released version |

They are the same chart, and the published one is packaged from a **separate staged copy**
rather than from the working tree (see `.github/workflows/publish.yaml`). That copy exists so
a fork publishing under its own Docker Hub namespace gets a chart pointing at its own images,
and so a publish-time rewrite can never leak back into the committed chart — the job asserts
the checkout is still clean afterwards.

Deploying a commit rather than a release is the case that needs extra values, because those
images only exist in GHCR. That is what `values-config.yaml` carries.

### From Docker Hub (a released version)

```bash
helm install rag oci://registry-1.docker.io/nuvraxis/rag-platform --version 1.2.3 \
  --namespace rag --create-namespace \
  --values my-values.yaml
```

No pull secret is needed: those images are public. The chart pins `image.tag` to its own
`appVersion`, so a release installs exactly the four images that were built alongside it and
`helm rollback` moves the running images back with it. `latest` exists on the registry for
`docker pull`, and is deliberately not what a Deployment resolves to.

## Install

```bash
cp infra/helm/values-secrets.example.yaml infra/helm/values-secrets.yaml   # then fill it in

helm upgrade --install rag infra/helm/rag-platform \
  --namespace rag --create-namespace \
  --set image.tag=0.1.0 \
  --values infra/helm/values-config.yaml \
  --values infra/helm/values-secrets.yaml
```

Two files, split by whether the contents can be read by anyone:

| File | Holds | Committed |
|---|---|---|
| `values-config.yaml` | hostnames, image, storage, sizing | yes — it is the reviewable record |
| `values-config.staging.yaml` | only what staging changes | yes |
| `values-secrets.yaml` | DSNs, JWT key, API keys | **no**, gitignored |
| `values-secrets.example.yaml` | the key names, no values | yes |

A second environment layers the staging overlay in between, under its own release name — the
tailnet device names derive from it, so two releases sharing one would fight over a device:

```bash
helm upgrade --install rag-local infra/helm/rag-platform --namespace rag  --values infra/helm/values-config.yaml --values infra/helm/values-config.yaml --values infra/helm/values-secrets.yaml
```

`image.tag` is required in practice: it defaults to `Chart.appVersion`, which is fine for a
first look and wrong for anything you intend to roll back.

The GHCR images are private until you publish them, so a cluster pulling from there needs a
pull secret (the Docker Hub images published by `publish.yaml` are public and need none):

```bash
kubectl create secret docker-registry ghcr -n rag \
  --docker-server=ghcr.io --docker-username="$GITHUB_USER" --docker-password="$GITHUB_PAT"
# then: --set image.pullSecrets[0].name=ghcr
```

`release.yml` pushes a `sha-<commit>` tag for every commit on `main`, which is the shape
`values-config.yaml` pins. `publish.yaml` pushes semver tags to Docker Hub when a release is
published.

## Ingress

Three origins have to be reachable, and they must be three different hostnames — the widget
is served cross-origin to tenant sites on purpose, and the dashboard's CORS origin is derived
from its own. The default shape is one host-routed Ingress carrying all three, under whatever
controller the cluster runs:

```yaml
ingress:
  enabled: true
  className: nginx           # or traefik, or whatever you run
  hosts:
    dashboard: { enabled: true, host: rag.example.com }
    api:       { enabled: true, host: rag-api.example.com }
    widget:    { enabled: true, host: rag-widget.example.com }
  tls:
    enabled: true            # cert-manager, usually
    secretName: rag-platform-tls
```

The `example.com` hosts in `values.yaml` are placeholders and will not serve anything — set
all three. The rendered Ingress carries `proxy-buffering: off` and a 300s read timeout,
because chat answers stream token by token over SSE and a buffering proxy would hold the
whole reply back until it finished.

`ingress.enabled: false` emits no Ingress at all, and the application keeps its localhost
defaults, which is what a port-forwarded install is actually reached on.

## Ingress over Tailscale

`ingress.className: tailscale` switches the chart to the operator's shape. That shape is not
the usual one: the operator gives **each Ingress its own tailnet device** and reads the
MagicDNS name from `spec.tls[0].hosts[0]`, not from a rule host. One Ingress with three host
rules would match the Host header against names the tailnet never sends, so the chart emits
three Ingresses — one per origin — and no `secretName`, because Tailscale issues the
certificate itself.

```yaml
ingress:
  className: tailscale
  tailnet: tail1a2b3.ts.net    # admin console → DNS
  hosts:
    dashboard: { enabled: true, host: rag,        funnel: false }
    api:       { enabled: true, host: rag-api,    funnel: false }
    widget:    { enabled: true, host: rag-widget, funnel: false }
```

That serves the dashboard at `https://rag.tail1a2b3.ts.net`. Set any other class name and the
chart falls back to a single host-routed Ingress with the nginx buffering annotations, for a
cluster that is not on a tailnet.

`ingress.tailnet` does one more job: `DASHBOARD_BASE_URL`, the CORS origin and the widget CDN
URL are derived from it whenever the matching `config.*` value is blank. Those three must
agree with the address the browser actually used, and deriving them removes the failure where
sign-in breaks with an error that points nowhere near the cause. Set the `config.*` value to
override.

### Reaching it from outside the tailnet

A widget embedded on a tenant's public site runs in a visitor's browser, which is not on your
tailnet — so both the **widget origin and the API** have to be publicly reachable for an embed
to work. `funnel: true` on those two exposes them through Tailscale Funnel:

```yaml
ingress:
  hosts:
    api:    { funnel: true }
    widget: { funnel: true }
```

Funnel needs the node attribute in your tailnet policy, or the operator leaves the Ingress
unprogrammed with no obvious complaint:

```json
"nodeAttrs": [{ "target": ["tag:k8s"], "attr": ["funnel"] }]
```

Leave the dashboard on `funnel: false`. It is the admin surface and has no reason to be on the
public internet.

`ingress.proxyGroup` and `ingress.proxyClass` pass through to the operator's
`tailscale.com/proxy-group` and `tailscale.com/proxy-class` annotations when you want highly
available ingress proxies or customised proxy pods.

## Secrets

`values-secrets.yaml` is gitignored — by name, so a copy of it anywhere in the repository is
ignored too. `values-secrets.example.yaml` is committed beside it as the record of which keys
a release expects. Fill the first, pass it last, and keep values out of the second.

Anything passed that way is readable through `helm get values rag`, which is fine on a cluster
you administer alone. Where it is not, create the Secret out of band and set
`secrets.create: false`:

```bash
kubectl create secret generic rag-platform-secrets -n rag \
  --from-literal=DB_CONNECTION_STRING=... \
  --from-literal=SECURITY_JWT_SECRET="$(openssl rand -base64 48)"
```

Either way every backend pod reads it through `envFrom`, so the two routes are
interchangeable from the application's point of view.

## Object storage

`config.storage.backend` defaults to `s3`, pointing at an in-cluster MinIO. `local` is a
per-pod directory: the worker cannot read what the API wrote unless it is an RWX volume, so it
only works with a single replica of each. `azure_blob` is still supported by the application
and needs `STORAGE_AZURE_CONNECTION_STRING` in the Secret.

## No ServiceAccount

Nothing in this chart talks to the Kubernetes API, so there is no ServiceAccount and every pod
sets `automountServiceAccountToken: false`. Dropping the ServiceAccount alone would have been
a step backwards — pods would fall back to `default`, whose token *is* mounted by default.

## Pod UIDs

`runAsNonRoot` is checked by the kubelet before the container starts, and it cannot prove that
a user an image names rather than numbers is not root — `USER app` is refused outright with
"non-numeric user". So each component declares its UID:

| Component | UID | From |
|---|---|---|
| api, worker, beat, migrate | 1001 | `app`, created in `api.Dockerfile` |
| dashboard | 1000 | `node`, in the `node:24-alpine` base |
| widget | 101 | `nginx`, in `nginxinc/nginx-unprivileged` |

The Dockerfiles now write these numerically too, so a freshly built image needs no help from
the chart. `<component>.podSecurityContext` merges over the shared `podSecurityContext`, which
is where `runAsNonRoot` and the seccomp profile live. Change one and change the other.

## Migrations

The `pre-install,pre-upgrade` hook runs `alembic upgrade head` in the API image and must
succeed before any pod rolls. That is what keeps a new replica from starting against a schema
it does not know, and stops two replicas racing each other over the same revision.

The Job name carries the release revision, so a failed migration stays on the cluster:

```bash
kubectl logs -n rag job/rag-rag-platform-migrate-7
```

Being a hook means it runs before the release's own ConfigMap and Secret are applied, which on
a first install do not exist yet. So the Job brings its own `-migrate` copies of both, at a
lower hook weight, carrying the same payload from the same template. Helm honours
`hook-delete-policy: hook-succeeded` only once every hook of the event has finished, so they
survive until the Job is done and are then removed. A failed migration keeps them, so the Job
can be read with its environment intact.

## The scheduler, and conversation retention

`beat.enabled` (on by default) adds a **one-replica** Deployment running `celery beat`. It is
the only thing that applies a chatbot's `retention_days`, and nothing else is on its schedule.

One replica is not a default to raise — it is the only correct value. Two schedulers enqueue
every task twice, so the chart deliberately offers no `replicaCount` and no autoscaler, and
uses the `Recreate` strategy so a rolling update never overlaps two of them.

Turning it off is a supported choice with one sharp edge worth stating plainly: the dashboard
still offers the retention field, and a tenant who sets it is told their conversations are
deleted after N days. Without beat they are not. The chart prints a warning on install when
`beat.enabled` is false, and the ConfigMap derives `RETENTION_ENABLED` from the same value so
the two can never disagree.

```yaml
beat:
  enabled: true
  schedule:
    hourUtc: 3       # UTC, not cluster-local
    minuteUtc: 30
```

The sweep runs on the `default` queue, not `ingestion`, so a tenant bulk-uploading documents
cannot leave it stuck behind their backlog. Each firing carries a six-hour expiry: a week with
no worker running discards the stale sweeps rather than running seven of them at once.

Beat writes its last-run times to a shelve file, which the chart puts in an `emptyDir` at
`/tmp` — the working directory is not writable under `readOnlyRootFilesystem`. Losing that
file on a restart is harmless, because a crontab schedule is computed from the clock.

## Scaling

Autoscaling is off by default: on a small cluster a fixed replica count is the right answer,
and a PodDisruptionBudget of `minAvailable: 1` against a single replica blocks `kubectl drain`
outright. k3s bundles metrics-server, so the HPAs work as soon as you enable them.

Ingestion is bound by the embedding API, not by CPU: the worker sits idle waiting on network
while a backlog builds, so a CPU-driven HPA scales *down* exactly when the queue needs
draining. With KEDA installed, use queue depth instead:

```yaml
worker:
  keda:
    enabled: true
    listName: ingestion
    listLength: "20"
```

`worker.autoscaling.enabled` still works without KEDA, and the two are mutually exclusive in
the templates.

## Before production traffic

- Run the API as a **non-owner** Postgres role. Row-level security does not apply to the table
  owner, so with a single role the policies are inert and only application-level filtering
  protects tenants. Point `DB_PRIVILEGED_DSN` at the owner for migrations and pre-login
  lookups.
- Set a real `SECURITY_JWT_SECRET`; the default is a development value.
- Set `AI_CREDENTIALS_ENCRYPTION_KEY` in the Secret. It has no default and the API will not
  start without one. It encrypts the provider API keys tenants enter in the dashboard, so
  back it up with the database password — rotating it leaves every stored credential
  unreadable, and each tenant has to re-enter theirs.
- Nothing here names an AI provider. Azure, Bedrock, Anthropic and Ollama are chosen per
  chatbot in the dashboard and stored in the database, so one release serves tenants on all
  four at once.
- Put a CDN in front of the widget host if tenant sites will carry real traffic. The nginx
  origin is sized to be a CDN origin, and Funnel is not a CDN.
