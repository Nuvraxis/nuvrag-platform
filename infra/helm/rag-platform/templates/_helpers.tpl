{{- define "rag.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "rag.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "rag.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "rag.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "rag.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "rag.selectorLabels" -}}
app.kubernetes.io/name: {{ include "rag.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Public URL of a component. An explicit value under `config` always wins; otherwise it is
derived from the ingress host, so DASHBOARD_BASE_URL and the CORS origin cannot drift away
from the address the operator actually serves — a mismatch there breaks sign-in with an error
that points nowhere near the cause.
*/}}
{{- define "rag.publicUrl" -}}
{{- $root := index . 0 -}}
{{- $host := (index $root.Values.ingress.hosts (index . 1)).host -}}
{{- if and (eq $root.Values.ingress.className "tailscale") $root.Values.ingress.tailnet -}}
{{- printf "https://%s.%s" $host (trimSuffix "." $root.Values.ingress.tailnet) -}}
{{- else -}}
{{- printf "https://%s" $host -}}
{{- end -}}
{{- end -}}

{{/*
Image reference for a component. The tag falls back to the chart's appVersion so a release
that forgets to set one is still pinned to something reproducible rather than `latest`.
*/}}
{{- define "rag.image" -}}
{{- $root := index . 0 -}}
{{- $component := index . 1 -}}
{{- $tag := default $root.Chart.AppVersion $root.Values.image.tag -}}
{{- printf "%s/%s-%s:%s" $root.Values.image.registry $root.Values.image.repository $component $tag -}}
{{- end -}}

{{/*
Pod security context for one component. The kubelet enforces `runAsNonRoot` before the
container starts and cannot verify a user an image names rather than numbers: `USER app` is
refused outright with "non-numeric user". The UID therefore has to be stated here, and it is
per component because the three images do not share one.
*/}}
{{- define "rag.podSecurityContext" -}}
{{- $shared := index . 0 -}}
{{- $component := default dict (index . 1) -}}
{{- toYaml (mergeOverwrite (deepCopy $shared) $component) -}}
{{- end -}}

{{/*
Environment shared by the API and the worker — the whole backend reads the same settings, and
drift between them is a class of bug worth designing out. The migration Job cannot use this:
it runs as a pre-install hook, before either of these objects exists.
*/}}
{{- define "rag.backendEnv" -}}
envFrom:
  - configMapRef:
      name: {{ include "rag.fullname" . }}-config
  - secretRef:
      name: {{ .Values.secrets.existingSecret }}
{{- end -}}

{{/*
The ConfigMap payload, defined once so the release's ConfigMap and the migration hook's
short-lived copy cannot drift apart.
*/}}
{{- define "rag.configData" -}}
ENVIRONMENT: {{ .Values.config.environment | quote }}
DOCS_ENABLED: {{ .Values.config.docsEnabled | quote }}

{{- /* Left blank in values, these follow the ingress hosts. Sign-in breaks in confusing ways
when the dashboard's own idea of its address disagrees with the one it is served on. With no
ingress they are omitted, so the application keeps its localhost defaults — which is what a
port-forwarded install is actually reached on. */}}
{{- if or .Values.config.dashboardBaseUrl .Values.ingress.enabled }}
DASHBOARD_BASE_URL: {{ .Values.config.dashboardBaseUrl | default (include "rag.publicUrl" (list . "dashboard")) | quote }}
{{- end }}
{{- if or .Values.config.dashboardCorsOrigins .Values.ingress.enabled }}
SECURITY_DASHBOARD_CORS_ORIGINS: {{ .Values.config.dashboardCorsOrigins | default (include "rag.publicUrl" (list . "dashboard")) | quote }}
{{- end }}
{{- if or .Values.config.widgetCdnBaseUrl .Values.ingress.enabled }}
WIDGET_CDN_BASE_URL: {{ .Values.config.widgetCdnBaseUrl | default (printf "%s/widget" (include "rag.publicUrl" (list . "widget"))) | quote }}
{{- end }}

STORAGE_BACKEND: {{ .Values.config.storage.backend | quote }}
STORAGE_CONTAINER: {{ .Values.config.storage.container | quote }}
{{- if eq .Values.config.storage.backend "s3" }}
STORAGE_S3_ENDPOINT_URL: {{ .Values.config.storage.s3.endpointUrl | quote }}
STORAGE_S3_REGION: {{ .Values.config.storage.s3.region | quote }}
{{- end }}
{{- if eq .Values.config.storage.backend "local" }}
STORAGE_LOCAL_ROOT: {{ .Values.config.storage.localRoot | quote }}
{{- end }}

{{- /* Which AI provider each chatbot uses is tenant configuration held in the database, not
a release value. All that belongs here is how hard the process tries. */}}
AI_EMBEDDING_BATCH_SIZE: {{ .Values.config.ai.embeddingBatchSize | quote }}
AI_REQUEST_TIMEOUT_SECONDS: {{ .Values.config.ai.requestTimeoutSeconds | quote }}
AI_MAX_RETRIES: {{ .Values.config.ai.maxRetries | quote }}

INGESTION_CLAMAV_HOST: {{ .Values.config.ingestion.clamavHost | quote }}
INGESTION_CLAMAV_PORT: {{ .Values.config.ingestion.clamavPort | quote }}

{{- /* Derived from `beat.enabled` rather than being a switch of its own. Two switches would
let an operator turn retention on with no scheduler deployed, which reads as "history is
deleted after 30 days" in the dashboard and deletes nothing. How long anything is kept is
still per chatbot, in the database — this only says whether the sweep is scheduled. */}}
RETENTION_ENABLED: {{ .Values.beat.enabled | quote }}
RETENTION_PURGE_HOUR_UTC: {{ .Values.beat.schedule.hourUtc | quote }}
RETENTION_PURGE_MINUTE_UTC: {{ .Values.beat.schedule.minuteUtc | quote }}

OTEL_SERVICE_NAME: {{ include "rag.fullname" . | quote }}
OTEL_TRACING_ENABLED: {{ .Values.config.observability.tracingEnabled | quote }}
OTEL_EXPORTER_OTLP_ENDPOINT: {{ .Values.config.observability.otlpEndpoint | quote }}
OTEL_LOG_LEVEL: {{ .Values.config.observability.logLevel | quote }}
OTEL_LOG_FORMAT: "json"
{{- end -}}

{{/*
The Secret payload, for the same reason. Blank values are dropped rather than written as
empty strings, which would override the application's own defaults with nothing.
*/}}
{{- define "rag.secretData" -}}
{{- range $key, $value := .Values.secrets.values }}
{{- if $value }}
{{ $key }}: {{ $value | quote }}
{{- end }}
{{- end }}
{{- end -}}
