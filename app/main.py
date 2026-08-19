from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.middleware import WidgetCORSMiddleware
from app.api.router import api_router, health_router, public_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engines
from app.observability.metrics import instrument_metrics
from app.observability.middleware import RequestContextMiddleware
from app.observability.tracing import configure_tracing, instrument_app
from app.services.redis_client import close_redis
from app.services.storage import close_object_storage

PUBLIC_PREFIX = "/public"

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    configure_logging(settings.observability)
    configure_tracing(settings.observability)
    logger.info(
        "api.startup",
        environment=settings.environment,
        storage_backend=settings.storage.backend,
    )
    try:
        yield
    finally:
        # Connections are closed explicitly so a rolling deploy drains rather than drops.
        await dispose_engines()
        await close_redis()
        await close_object_storage()
        logger.info("api.shutdown")


def create_app() -> FastAPI:
    docs_enabled = settings.docs_enabled and not settings.is_production

    app = FastAPI(
        title=settings.project_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    # Middleware is applied in reverse registration order, so the outermost layer is the one
    # added last. The intended chain is:
    #   RequestContext -> WidgetCORS -> dashboard CORS -> routes
    # WidgetCORS must sit outside the dashboard's CORSMiddleware: the latter answers every
    # preflight it sees and rejects any origin outside its static allow-list, which would
    # turn each tenant site's preflight into a 400 before the widget layer ever ran.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.security.dashboard_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(WidgetCORSMiddleware, prefix=PUBLIC_PREFIX)
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.include_router(public_router, prefix=PUBLIC_PREFIX)

    instrument_metrics(app, settings.observability)
    instrument_app(app, settings.observability)
    return app


app = create_app()
