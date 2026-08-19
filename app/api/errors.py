from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import DomainError, RateLimitExceededError
from app.core.logging import get_logger

logger = get_logger(__name__)


def _payload(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _field_path(location: tuple) -> str:
    """`('body', 'password')` reads better to an API consumer as just `password`."""
    parts = [str(part) for part in location if part not in {"body", "query", "path", "header"}]
    return ".".join(parts) or "body"


def _clean_message(message: str) -> str:
    """Pydantic prefixes messages raised by custom validators; the prefix is noise to a
    consumer reading the field's error."""
    for prefix in ("Value error, ", "Assertion failed, "):
        if message.startswith(prefix):
            return message[len(prefix) :]
    return message


def _validation_details(exc: RequestValidationError) -> list[dict[str, str]]:
    """Rebuild Pydantic's error list as plain JSON-safe entries.

    Two things must not survive this step. `ctx` carries the raw `ValueError` raised by a
    field validator, which is not JSON-serializable and turned every custom-validator failure
    into a 500. `input` echoes the submitted value back — which for a signup request is the
    user's plaintext password, in both the response body and the logs.
    """
    return [
        {
            "field": _field_path(error.get("loc", ())),
            "type": str(error.get("type", "invalid")),
            "message": _clean_message(str(error.get("msg", "Invalid value"))),
        }
        for error in exc.errors()
    ]


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        headers = {}
        if isinstance(exc, RateLimitExceededError):
            headers["Retry-After"] = str(exc.retry_after_seconds)
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(exc.code, exc.message, exc.details),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_payload(
                "validation_error",
                "The request failed validation",
                {"errors": _validation_details(exc)},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload("http_error", str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Log the detail, return none of it: an unhandled error must not leak internals.
        logger.exception(
            "request.unhandled_exception",
            path=request.url.path,
            error=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content=_payload("internal_error", "An unexpected error occurred"),
        )
