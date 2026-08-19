"""What each provider needs before it can be called.

Kept apart from the implementations so validation, the "is this chatbot ready" check and the
dashboard's error messages all read the same table, and so importing it costs nothing — none
of the provider SDKs are pulled in here.
"""

from dataclasses import dataclass

from app.models import ChatProviderName, EmbeddingProviderName


@dataclass(frozen=True, slots=True)
class Requirements:
    """`credentials` are write-only and encrypted; `connection` is stored in the clear."""

    credentials: tuple[str, ...]
    connection: tuple[str, ...]


CHAT_REQUIREMENTS: dict[ChatProviderName, Requirements] = {
    ChatProviderName.AZURE: Requirements(("api_key",), ("endpoint",)),
    ChatProviderName.BEDROCK: Requirements(("access_key_id", "secret_access_key"), ("region",)),
    ChatProviderName.ANTHROPIC: Requirements(("api_key",), ()),
    # Self-hosted, so there is nothing to authenticate with — the base URL is the whole of it.
    ChatProviderName.OLLAMA: Requirements((), ("base_url",)),
}

EMBEDDING_REQUIREMENTS: dict[EmbeddingProviderName, Requirements] = {
    EmbeddingProviderName.AZURE: Requirements(("api_key",), ("endpoint",)),
    EmbeddingProviderName.BEDROCK: Requirements(
        ("access_key_id", "secret_access_key"), ("region",)
    ),
    EmbeddingProviderName.OLLAMA: Requirements((), ("base_url",)),
}


def chat_requirements(provider: ChatProviderName) -> Requirements:
    return CHAT_REQUIREMENTS[ChatProviderName(provider)]


def embedding_requirements(provider: EmbeddingProviderName) -> Requirements:
    return EMBEDDING_REQUIREMENTS[EmbeddingProviderName(provider)]


def missing_credential_fields(
    requirements: Requirements, credentials: dict[str, str] | None
) -> list[str]:
    supplied = credentials or {}
    return [name for name in requirements.credentials if not supplied.get(name)]


def missing_connection_fields(
    requirements: Requirements, connection: dict[str, object] | None
) -> list[str]:
    supplied = connection or {}
    return [name for name in requirements.connection if not supplied.get(name)]


def is_ready(
    requirements: Requirements,
    *,
    has_stored_credentials: bool,
    connection: dict[str, object] | None,
) -> bool:
    """Whether a saved row has enough to make a call.

    Credentials are checked by presence rather than by field, because the only thing a stored
    row exposes about them is that there is a ciphertext — reading it to count keys would mean
    decrypting a secret to answer a question about configuration.
    """
    if requirements.credentials and not has_stored_credentials:
        return False
    return not missing_connection_fields(requirements, connection)
