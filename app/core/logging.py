import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

from app.core.config import ObservabilitySettings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
org_id_var: ContextVar[str | None] = ContextVar("org_id", default=None)
chatbot_id_var: ContextVar[str | None] = ContextVar("chatbot_id", default=None)

_CONTEXT_VARS = {
    "request_id": request_id_var,
    "org_id": org_id_var,
    "chatbot_id": chatbot_id_var,
}

_NOISY_LOGGERS = (
    "azure.core.pipeline.policies.http_logging_policy",
    "botocore",
    "aiobotocore",
    "httpx",
    "openai",
)


def _bind_request_context(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key, var in _CONTEXT_VARS.items():
        value = var.get()
        if value is not None:
            event_dict.setdefault(key, value)
    return event_dict


def configure_logging(config: ObservabilitySettings) -> None:
    """Route stdlib logging through structlog so every emitter shares one format."""
    level = logging.getLevelNamesMapping().get(config.log_level.upper(), logging.INFO)

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        _bind_request_context,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if config.log_format == "json":
        renderer: structlog.typing.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.ExceptionPrettyPrinter()
            if config.log_format == "console"
            else structlog.processors.format_exc_info,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    # uvicorn installs its own handlers; drop them so records reach the root handler once.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)
