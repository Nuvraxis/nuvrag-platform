from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_ALLOWED_METHODS = "GET, POST, OPTIONS"
_ALLOWED_HEADERS = "Content-Type, X-Chatbot-Key, X-Widget-Site, X-Widget-Session, X-Requested-With"
_PREFLIGHT_MAX_AGE = "600"


class WidgetCORSMiddleware:
    """Per-chatbot CORS for the widget API.

    Starlette's CORSMiddleware needs a static allow-list, but the permitted origins here
    belong to each chatbot's `allowed_origins`. The endpoint dependency is what actually
    authorises a request; this middleware only reflects the result back to the browser.

    Written as raw ASGI rather than BaseHTTPMiddleware so SSE responses stream through
    untouched instead of being buffered.
    """

    def __init__(self, app: ASGIApp, *, prefix: str) -> None:
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(self.prefix):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        origin = headers.get("origin")

        if scope["method"] == "OPTIONS" and "access-control-request-method" in headers:
            # A preflight cannot carry the chatbot key, so it is answered generically.
            # This grants nothing on its own: the real request is still checked against the
            # chatbot's allow-list before any work happens.
            await self._preflight(origin).__call__(scope, receive, send)
            return

        if origin is None:
            await self.app(scope, receive, send)
            return

        async def send_with_cors(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] < 400:
                response_headers = MutableHeaders(raw=message["headers"])
                response_headers.setdefault("access-control-allow-origin", origin)
                response_headers.append("vary", "Origin")
            await send(message)

        await self.app(scope, receive, send_with_cors)

    @staticmethod
    def _preflight(origin: str | None) -> Response:
        headers = {
            "Access-Control-Allow-Methods": _ALLOWED_METHODS,
            "Access-Control-Allow-Headers": _ALLOWED_HEADERS,
            "Access-Control-Max-Age": _PREFLIGHT_MAX_AGE,
            "Vary": "Origin",
        }
        if origin:
            headers["Access-Control-Allow-Origin"] = origin
        return Response(status_code=204, headers=headers)
