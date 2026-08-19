from typing import Any


class DomainError(Exception):
    """Base class for errors that map cleanly onto an HTTP response."""

    status_code: int = 400
    code: str = "domain_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class ValidationError(DomainError):
    status_code = 422
    code = "validation_error"


class AuthenticationError(DomainError):
    status_code = 401
    code = "unauthenticated"


class PermissionDeniedError(DomainError):
    status_code = 403
    code = "permission_denied"


class OriginNotAllowedError(DomainError):
    status_code = 403
    code = "origin_not_allowed"


class ChatbotUnavailableError(DomainError):
    """The chatbot exists but is paused or archived.

    Its own code rather than a bare `permission_denied`, because the widget acts on it: this
    is the answer that makes it remove itself from the page, and it must not be confused with
    a permission problem it should sit tight through. 403 rather than 404 — the public key is
    in the tenant's own HTML, so pretending the chatbot does not exist buys nothing.
    """

    status_code = 403
    code = "chatbot_unavailable"


class RateLimitExceededError(DomainError):
    status_code = 429
    code = "rate_limit_exceeded"

    def __init__(self, message: str, *, retry_after_seconds: int) -> None:
        super().__init__(message, details={"retry_after_seconds": retry_after_seconds})
        self.retry_after_seconds = retry_after_seconds


class PayloadTooLargeError(DomainError):
    status_code = 413
    code = "payload_too_large"


class UnsupportedMediaTypeError(DomainError):
    status_code = 415
    code = "unsupported_media_type"


class UpstreamServiceError(DomainError):
    """An external dependency (an AI provider, blob storage) failed."""

    status_code = 502
    code = "upstream_unavailable"


class ProviderNotConfiguredError(DomainError):
    """A chatbot was asked to embed or answer before anyone chose it a provider."""

    status_code = 422
    code = "ai_provider_not_configured"


class CredentialsUnreadableError(DomainError):
    """Stored provider credentials no longer decrypt — almost always a rotated
    AI_CREDENTIALS_ENCRYPTION_KEY."""

    status_code = 409
    code = "credentials_unreadable"


class DocumentProcessingError(DomainError):
    """Raised inside the ingestion pipeline; carries whether a retry is worthwhile."""

    status_code = 422
    code = "document_processing_failed"

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message, details={"retryable": retryable})
        self.retryable = retryable
