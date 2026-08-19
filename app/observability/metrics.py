from fastapi import FastAPI
from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.config import ObservabilitySettings

# Token usage and upstream latency are the cost driver and the quality signal at once, so
# they are tracked per chatbot rather than only in aggregate.
llm_tokens_total = Counter(
    "rag_llm_tokens_total",
    "Tokens consumed by Azure AI Foundry calls",
    labelnames=("chatbot_id", "kind"),
)

llm_request_seconds = Histogram(
    "rag_llm_request_seconds",
    "Latency of Azure AI Foundry calls",
    labelnames=("operation",),
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)

ingestion_documents_total = Counter(
    "rag_ingestion_documents_total",
    "Documents leaving the ingestion pipeline",
    labelnames=("outcome",),
)

ingestion_duration_seconds = Histogram(
    "rag_ingestion_duration_seconds",
    "Wall-clock time to ingest one document",
    buckets=(1, 5, 15, 30, 60, 120, 300, 600),
)

retrieval_chunks = Histogram(
    "rag_retrieval_chunks",
    "Chunks passing the similarity threshold per query",
    buckets=(0, 1, 2, 3, 5, 8, 13, 20),
)

widget_requests_total = Counter(
    "rag_widget_requests_total",
    "Widget chat requests by outcome",
    labelnames=("outcome",),
)


def instrument_metrics(app: FastAPI, config: ObservabilitySettings) -> None:
    if not config.metrics_enabled:
        return
    Instrumentator(
        should_group_status_codes=False,
        excluded_handlers=["/metrics", "/health"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
