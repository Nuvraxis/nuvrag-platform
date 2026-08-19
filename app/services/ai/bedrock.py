"""Amazon Bedrock, via the Converse API.

Static access keys only. Cross-account role assumption would mean holding a trust
relationship rather than a credential, which is a different feature.
"""

from typing import Any

from langchain_aws import BedrockEmbeddings, ChatBedrockConverse

from app.services.ai.base import (
    ChatProvider,
    EmbeddingProvider,
    GenerationParams,
    LangChainChat,
    LangChainEmbeddings,
)

PROVIDER = "bedrock"


def _session(config: dict[str, Any], credentials: dict[str, str]) -> dict[str, Any]:
    return {
        "region_name": str(config.get("region") or "") or None,
        "aws_access_key_id": credentials.get("access_key_id"),
        "aws_secret_access_key": credentials.get("secret_access_key"),
        # Set only for a VPC endpoint or a local emulator; otherwise boto3 derives it.
        "endpoint_url": str(config.get("endpoint") or "") or None,
    }


def build_chat(
    *,
    model: str,
    config: dict[str, Any],
    credentials: dict[str, str],
    params: GenerationParams,
) -> ChatProvider:
    return LangChainChat(
        ChatBedrockConverse(
            model_id=model,
            temperature=params.temperature,
            max_tokens=params.max_tokens,
            **_session(config, credentials),
        ),
        provider=PROVIDER,
    )


def build_embeddings(
    *,
    model: str,
    config: dict[str, Any],
    credentials: dict[str, str],
    dimension: int | None,
) -> EmbeddingProvider:
    return LangChainEmbeddings(
        BedrockEmbeddings(model_id=model, **_session(config, credentials)),
        provider=PROVIDER,
        dimension=dimension,
    )
