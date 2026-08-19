from fastapi import FastAPI

from app.core.config import ObservabilitySettings
from app.core.logging import get_logger

logger = get_logger(__name__)

_configured = False


def configure_tracing(config: ObservabilitySettings) -> None:
    """Wire OpenTelemetry once per process.

    Spans cross FastAPI, SQLAlchemy, Redis and Celery, so a slow chat response can be traced
    end-to-end — including the Azure AI Foundry call — instead of being guessed at.
    """
    global _configured
    if _configured or not config.tracing_enabled:
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": config.service_name}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=config.exporter_otlp_endpoint))
    )
    trace.set_tracer_provider(provider)

    _instrument_clients()
    _configured = True
    logger.info("tracing.configured", endpoint=config.exporter_otlp_endpoint)


def _instrument_clients() -> None:
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    from app.db.session import get_engine

    RedisInstrumentor().instrument()
    SQLAlchemyInstrumentor().instrument(engine=get_engine().sync_engine)


def instrument_app(app: FastAPI, config: ObservabilitySettings) -> None:
    if not config.tracing_enabled:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics")


def instrument_celery() -> None:
    from opentelemetry.instrumentation.celery import CeleryInstrumentor

    CeleryInstrumentor().instrument()
