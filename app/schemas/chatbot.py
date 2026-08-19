from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import ChatbotStatus
from app.models.chatbot import LINK_MAX_LENGTH, RETENTION_MAX_DAYS, RETENTION_MIN_DAYS


def validate_link(value: str) -> str:
    """A footer link, or an empty string for none.

    The widget turns these into anchors a visitor clicks, so the scheme is the whole of the
    security question: `javascript:` and `data:` are refused here, and refused again by the
    widget's own `safeUrl` before an `href` is ever set. Two checks rather than one because
    the value crosses a JSONB column, a Redis cache and a public endpoint in between.
    """
    link = value.strip()
    if not link:
        return ""

    parsed = urlparse(link)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Link {value!r} must start with https:// or http://")
    if not parsed.netloc:
        raise ValueError(
            f"Link {value!r} is missing a domain; expected https://example.com/privacy"
        )
    return link


def link_field(description: str) -> Any:
    return Field(default="", max_length=LINK_MAX_LENGTH, description=description)


PRIVACY_DESCRIPTION = (
    "Absolute URL of the tenant's privacy policy, shown in the widget footer. "
    "Empty string for no link."
)
TERMS_DESCRIPTION = (
    "Absolute URL of the tenant's terms, shown in the widget footer. Empty string for no link."
)

RETENTION_DESCRIPTION = (
    "Days of visitor conversation history to keep, counted from a conversation's last "
    "activity. Null keeps transcripts indefinitely, which is the default. A conversation "
    "held open by an unresolved ticket is never purged."
)


def retention_field() -> Any:
    return Field(
        default=None,
        ge=RETENTION_MIN_DAYS,
        le=RETENTION_MAX_DAYS,
        description=RETENTION_DESCRIPTION,
    )


def _validate_origins(value: list[str]) -> list[str]:
    """Origins are compared against the browser's `Origin` header, which is always
    scheme://host[:port] with no path or trailing slash."""
    cleaned: list[str] = []
    for raw in value:
        origin = raw.strip().rstrip("/")
        if origin == "*":
            raise ValueError(
                "Wildcard origins are not allowed; list each embedding site explicitly"
            )
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Invalid origin {raw!r}; expected https://example.com")
        if parsed.path or parsed.query or parsed.fragment:
            raise ValueError(f"Origin {raw!r} must not include a path or query string")
        cleaned.append(f"{parsed.scheme}://{parsed.netloc}")
    return sorted(set(cleaned))


HEX_COLOUR = r"^#[0-9a-fA-F]{6}$"


class WidgetTheme(BaseModel):
    """How the widget looks on the tenant's site.

    Every member is optional and only what was set is persisted. The widget applies these as
    inline custom properties over its own stylesheet, so an unset colour keeps the default —
    including the automatic dark-mode switch — while a set one wins outright.

    Six digits of hex, no shorthand and no `rgb()`: the values are interpolated into a style
    attribute, and a narrow pattern is easier to be sure of than an escaping routine.
    """

    model_config = ConfigDict(extra="forbid")

    accent: str | None = Field(default=None, pattern=HEX_COLOUR)
    accent_foreground: str | None = Field(default=None, pattern=HEX_COLOUR)
    surface: str | None = Field(default=None, pattern=HEX_COLOUR)
    surface_muted: str | None = Field(default=None, pattern=HEX_COLOUR)
    border: str | None = Field(default=None, pattern=HEX_COLOUR)
    text: str | None = Field(default=None, pattern=HEX_COLOUR)
    text_muted: str | None = Field(default=None, pattern=HEX_COLOUR)

    radius: int | None = Field(default=None, ge=0, le=28)
    scheme: Literal["system", "light", "dark"] | None = None
    position: Literal["right", "left"] | None = None

    title: str | None = Field(default=None, max_length=60)
    greeting: str | None = Field(default=None, max_length=300)


class GenerationConfig(BaseModel):
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=64, le=8192)
    top_k: int = Field(default=5, ge=1, le=20)
    min_similarity: float = Field(default=0.25, ge=0.0, le=1.0)


class ChatbotCreate(BaseModel):
    # `slug` is derived from `name` on the server and is never accepted from a client, so a
    # tenant cannot collide with, guess at, or squat on another chatbot's identifier.
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    system_prompt: str = Field(default="", max_length=8000)
    allowed_origins: list[str] = Field(default_factory=list, max_length=50)
    model_config_json: GenerationConfig = Field(default_factory=GenerationConfig)
    theme_json: WidgetTheme = Field(default_factory=WidgetTheme)
    retention_days: int | None = retention_field()
    privacy_url: str = link_field(PRIVACY_DESCRIPTION)
    terms_url: str = link_field(TERMS_DESCRIPTION)

    model_config = ConfigDict(protected_namespaces=())

    @field_validator("allowed_origins")
    @classmethod
    def check_origins(cls, value: list[str]) -> list[str]:
        return _validate_origins(value)

    @field_validator("privacy_url", "terms_url")
    @classmethod
    def check_links(cls, value: str) -> str:
        return validate_link(value)


class ChatbotUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    system_prompt: str | None = Field(default=None, max_length=8000)
    allowed_origins: list[str] | None = Field(default=None, max_length=50)
    model_config_json: GenerationConfig | None = None
    theme_json: WidgetTheme | None = None
    status: ChatbotStatus | None = None
    # The one field on this model where an explicit `null` is a value rather than an
    # omission: it is how a tenant turns retention back off. `update_chatbot` reinstates it
    # for exactly that reason — see the comment there.
    retention_days: int | None = retention_field()
    # `None` is "unchanged" and `""` is "remove the link", the same split as `description`.
    privacy_url: str | None = Field(default=None, max_length=LINK_MAX_LENGTH)
    terms_url: str | None = Field(default=None, max_length=LINK_MAX_LENGTH)

    model_config = ConfigDict(protected_namespaces=())

    @field_validator("allowed_origins")
    @classmethod
    def check_origins(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _validate_origins(value)

    @field_validator("privacy_url", "terms_url")
    @classmethod
    def check_links(cls, value: str | None) -> str | None:
        return None if value is None else validate_link(value)


class ChatbotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: UUID
    org_id: UUID
    name: str
    slug: str
    description: str | None
    system_prompt: str
    allowed_origins: list[str]
    model_config_json: dict[str, Any]
    theme_json: dict[str, Any]
    retention_days: int | None
    privacy_url: str
    terms_url: str
    public_key: str
    status: ChatbotStatus
    created_at: datetime
    updated_at: datetime


class ChatbotSecret(BaseModel):
    """The plaintext secret is returned exactly once, at creation or rotation."""

    chatbot_id: UUID
    secret_key: str


class ChatbotCreateResponse(BaseModel):
    chatbot: ChatbotRead
    secret: ChatbotSecret


class EmbedSnippet(BaseModel):
    public_key: str
    loader_url: str
    snippet: str
