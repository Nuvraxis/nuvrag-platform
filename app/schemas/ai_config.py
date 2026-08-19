from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import ChatProviderName, EmbeddingProviderName
from app.services.ai.registry import (
    chat_requirements,
    embedding_requirements,
    missing_connection_fields,
)


class ProviderCredentials(BaseModel):
    """Write-only, in the same sense the chatbot's secret key is: it goes in and never comes
    back out. Which members matter depends on the provider — see `registry.py`."""

    model_config = ConfigDict(extra="forbid")

    api_key: str | None = Field(default=None, max_length=512)
    access_key_id: str | None = Field(default=None, max_length=128)
    secret_access_key: str | None = Field(default=None, max_length=512)

    def as_dict(self) -> dict[str, str]:
        return {key: value for key, value in self.model_dump().items() if value}


class ProviderConnection(BaseModel):
    """Non-secret connection detail. Stored in the clear and returned to the dashboard."""

    model_config = ConfigDict(extra="forbid")

    endpoint: str | None = Field(default=None, max_length=500)
    api_version: str | None = Field(default=None, max_length=40)
    region: str | None = Field(default=None, max_length=40)
    base_url: str | None = Field(default=None, max_length=500)

    @field_validator("endpoint", "base_url")
    @classmethod
    def check_url(cls, value: str | None) -> str | None:
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("Must be an http:// or https:// URL")
        return value


class ChatConnection(ProviderConnection):
    # Only Ollama acts on this today. The other providers accept and ignore it rather than
    # rejecting a field a tenant may have set before switching provider.
    think: bool = True


class ChatTarget(BaseModel):
    """One half of a configuration: what to call and how to reach it."""

    model_config = ConfigDict(extra="forbid")

    provider: ChatProviderName
    model: str = Field(min_length=1, max_length=200)
    connection: ChatConnection = Field(default_factory=ChatConnection)
    credentials: ProviderCredentials | None = None


class EmbeddingTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: EmbeddingProviderName
    model: str = Field(min_length=1, max_length=200)
    connection: ProviderConnection = Field(default_factory=ProviderConnection)
    credentials: ProviderCredentials | None = None

    @field_validator("provider", mode="before")
    @classmethod
    def reject_anthropic(cls, value: object) -> object:
        """The enum has no member for it, but the bare enum error would only list what *is*
        allowed. This is the one rule a tenant is most likely to try, so it gets a reason."""
        if isinstance(value, str) and value.lower() == "anthropic":
            raise ValueError(
                "Anthropic publishes no embeddings API. Choose azure, bedrock or ollama for "
                "embeddings; Anthropic can still answer questions as the chat provider."
            )
        return value


class AIConfigUpdate(BaseModel):
    """A whole configuration, replaced in one call.

    Credentials may be omitted to keep the ones already stored, which is what lets a model or
    an endpoint be corrected without re-typing a key that was never readable back.
    """

    model_config = ConfigDict(extra="forbid")

    chat: ChatTarget
    embedding: EmbeddingTarget

    @model_validator(mode="after")
    def check_connection_details(self) -> AIConfigUpdate:
        chat_missing = missing_connection_fields(
            chat_requirements(self.chat.provider), self.chat.connection.model_dump()
        )
        if chat_missing:
            raise ValueError(
                f"{self.chat.provider} chat needs {_join(chat_missing)} in `chat.connection`"
            )

        embedding_missing = missing_connection_fields(
            embedding_requirements(self.embedding.provider), self.embedding.connection.model_dump()
        )
        if embedding_missing:
            raise ValueError(
                f"{self.embedding.provider} embeddings need {_join(embedding_missing)} in "
                "`embedding.connection`"
            )
        return self


class AIConfigTest(BaseModel):
    """An in-flight configuration, not necessarily the saved one.

    Credentials are optional for the same reason they are optional on a save: a test should
    exercise *what would be saved*, and for an omitted credential that is the one already
    stored. Requiring them here would mean re-typing a key that cannot be read back merely to
    correct a model name. The service resolves the fallback and only accepts it when the
    provider still matches — a key stored for Azure proves nothing about Bedrock.
    """

    model_config = ConfigDict(extra="forbid")

    chat: ChatTarget | None = None
    embedding: EmbeddingTarget | None = None

    @model_validator(mode="after")
    def check_something_to_test(self) -> AIConfigTest:
        if self.chat is None and self.embedding is None:
            raise ValueError("Provide `chat`, `embedding`, or both")

        for label, target, requirements in (
            ("chat", self.chat, self.chat and chat_requirements(self.chat.provider)),
            (
                "embedding",
                self.embedding,
                self.embedding and embedding_requirements(self.embedding.provider),
            ),
        ):
            if target is None or requirements is None:
                continue
            missing = missing_connection_fields(requirements, target.connection.model_dump())
            if missing:
                raise ValueError(f"{target.provider} {label} needs {_join(missing)}")
        return self


class ProviderRead(BaseModel):
    """What the dashboard is told about one half. No credential ever appears here."""

    provider: str
    model: str
    connection: dict[str, Any]
    credentials_set: bool
    ready: bool


class AIConfigRead(BaseModel):
    chat: ProviderRead
    embedding: ProviderRead
    # Null until a real call has measured it. Once set, the embedding provider and model are
    # frozen for as long as the chatbot has chunks.
    embedding_dimension: int | None
    embedding_locked: bool


class AIConfigTestResult(BaseModel):
    ok: bool
    embedding_dimension: int | None = None
    # Always one of a fixed set of phrases. A provider's own error text can quote the
    # credential it just rejected, so none of it is forwarded.
    error: str | None = None
    failed: Literal["chat", "embedding"] | None = None


def _join(names: list[str]) -> str:
    return ", ".join(f"`{name}`" for name in names)
