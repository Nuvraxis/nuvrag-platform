import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import chatbot_id_var, get_logger, org_id_var, request_id_var

logger = get_logger("app.request")

REQUEST_ID_HEADER = "X-Request-ID"
_QUIET_PATHS = frozenset({"/health", "/health/live", "/health/ready", "/metrics"})


class RequestContextMiddleware:
    """Assigns a request id, binds it to the logging context, and logs one line per request.

    Raw ASGI so that streaming responses are not buffered on their way out.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(REQUEST_ID_HEADER.lower().encode())
        request_id = incoming.decode() if incoming else uuid.uuid4().hex

        structlog.contextvars.clear_contextvars()
        request_id_var.set(request_id)
        org_id_var.set(None)
        chatbot_id_var.set(None)

        path = scope.get("path", "")
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(raw=message["headers"]).setdefault(REQUEST_ID_HEADER, request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if path not in _QUIET_PATHS:
                logger.info(
                    "http.request",
                    method=scope.get("method"),
                    path=path,
                    status_code=status_code,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
