import json
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.logging import get_logger
from app.models import Chatbot

logger = get_logger(__name__)

_CHATBOT_BY_KEY = "chatbot:pk:{public_key}"
_AI_CONFIG = "chatbot:ai:{chatbot_id}"


def _serialise(chatbot: Chatbot) -> str:
    return json.dumps(
        {
            "id": str(chatbot.id),
            "org_id": str(chatbot.org_id),
            "name": chatbot.name,
            "system_prompt": chatbot.system_prompt,
            "model_config_json": chatbot.model_config_json,
            "allowed_origins": chatbot.allowed_origins,
            "theme_json": chatbot.theme_json,
            "privacy_url": chatbot.privacy_url,
            "terms_url": chatbot.terms_url,
            "status": str(chatbot.status),
            "monthly_retrieval_call_cap": chatbot.monthly_retrieval_call_cap,
            "usage_cap_message": chatbot.usage_cap_message,
        }
    )


class ChatbotConfigCache:
    """Every widget message would otherwise start with a chatbot lookup on the primary.

    Chatbot settings change rarely, so a short TTL plus explicit invalidation on update keeps
    the read path off the database without letting stale config linger.
    """

    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def get_by_public_key(self, public_key: str) -> dict[str, Any] | None:
        try:
            raw = await self._redis.get(_CHATBOT_BY_KEY.format(public_key=public_key))
        except RedisError as exc:
            logger.warning("cache.read_failed", public_key=public_key, error=str(exc))
            return None
        return json.loads(raw) if raw else None

    async def set_by_public_key(self, chatbot: Chatbot) -> None:
        try:
            await self._redis.set(
                _CHATBOT_BY_KEY.format(public_key=chatbot.public_key),
                _serialise(chatbot),
                ex=self._ttl,
            )
        except RedisError as exc:
            logger.warning("cache.write_failed", chatbot_id=str(chatbot.id), error=str(exc))

    async def invalidate(self, public_key: str) -> None:
        try:
            await self._redis.delete(_CHATBOT_BY_KEY.format(public_key=public_key))
        except RedisError as exc:
            logger.warning("cache.invalidate_failed", public_key=public_key, error=str(exc))

    async def invalidate_many(self, public_keys: list[str]) -> None:
        if not public_keys:
            return
        try:
            await self._redis.delete(
                *[_CHATBOT_BY_KEY.format(public_key=key) for key in public_keys]
            )
        except RedisError as exc:
            logger.warning("cache.invalidate_failed", count=len(public_keys), error=str(exc))


class AIConfigCache:
    """The non-secret half of a chatbot's provider configuration.

    Which provider, which model and how wide its vectors are gets asked on the upload path
    and again on every chat turn. None of it is a credential, and none of it changes between
    saves, so it gets the same short TTL and explicit invalidation as the chatbot config.

    Credentials are never written here. They live in one place, encrypted, and are read from
    the database each time a provider is actually built.
    """

    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def get(self, chatbot_id: UUID) -> dict[str, Any] | None:
        try:
            raw = await self._redis.get(_AI_CONFIG.format(chatbot_id=chatbot_id))
        except RedisError as exc:
            logger.warning("cache.ai_read_failed", chatbot_id=str(chatbot_id), error=str(exc))
            return None
        return json.loads(raw) if raw else None

    async def set(self, chatbot_id: UUID, summary: dict[str, Any]) -> None:
        try:
            await self._redis.set(
                _AI_CONFIG.format(chatbot_id=chatbot_id), json.dumps(summary), ex=self._ttl
            )
        except RedisError as exc:
            logger.warning("cache.ai_write_failed", chatbot_id=str(chatbot_id), error=str(exc))

    async def invalidate(self, chatbot_id: UUID) -> None:
        try:
            await self._redis.delete(_AI_CONFIG.format(chatbot_id=chatbot_id))
        except RedisError as exc:
            logger.warning("cache.ai_invalidate_failed", chatbot_id=str(chatbot_id), error=str(exc))


def cached_chatbot_id(payload: dict[str, Any]) -> UUID:
    return UUID(payload["id"])


def cached_org_id(payload: dict[str, Any]) -> UUID:
    return UUID(payload["org_id"])
