from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.security import generate_public_key, generate_secret_key, hash_api_key
from app.core.slug import randomised_slug, slugify, unique_slug
from app.db.session import tenant_session
from app.models import Chatbot, ChatbotStatus
from app.repositories import ChatbotRepository
from app.schemas.chatbot import ChatbotCreate, ChatbotUpdate, EmbedSnippet
from app.services.cache import ChatbotConfigCache
from app.services.redis_client import get_redis

SLUG_MAX_LENGTH = 100


def _cache() -> ChatbotConfigCache:
    return ChatbotConfigCache(get_redis(), settings.redis.chatbot_cache_ttl_seconds)


def _build(org_id: UUID, payload: ChatbotCreate, slug: str, secret_key: str) -> Chatbot:
    return Chatbot(
        org_id=org_id,
        name=payload.name,
        slug=slug,
        description=payload.description,
        system_prompt=payload.system_prompt,
        allowed_origins=payload.allowed_origins,
        model_config_json=payload.model_config_json.model_dump(),
        # Only what was chosen. An absent key means the widget's own default, so a theme
        # saved today does not freeze in colours a later widget release would have moved.
        theme_json=payload.theme_json.model_dump(exclude_none=True),
        retention_days=payload.retention_days,
        privacy_url=payload.privacy_url,
        terms_url=payload.terms_url,
        public_key=generate_public_key(settings.environment),
        secret_key_hash=hash_api_key(secret_key),
    )


async def create_chatbot(org_id: UUID, payload: ChatbotCreate) -> tuple[Chatbot, str]:
    """The slug is derived from the name; two chatbots called "Support" become
    `support` and `support-2`."""
    secret_key = generate_secret_key(settings.environment)
    base = slugify(payload.name, max_length=SLUG_MAX_LENGTH, fallback="chatbot")

    try:
        async with tenant_session(org_id) as session:
            repo = ChatbotRepository(session)
            slug = await unique_slug(
                base,
                lambda candidate: repo.slug_exists(org_id, candidate),
                max_length=SLUG_MAX_LENGTH,
            )
            chatbot = await repo.add(_build(org_id, payload, slug, secret_key))
    except IntegrityError:
        # Two concurrent creates can both pass the availability check and pick the same
        # slug. The unique constraint is the real arbiter, so the loser retries with a
        # random suffix rather than failing a request the caller did nothing wrong in.
        async with tenant_session(org_id) as session:
            chatbot = await ChatbotRepository(session).add(
                _build(
                    org_id,
                    payload,
                    randomised_slug(base, max_length=SLUG_MAX_LENGTH),
                    secret_key,
                )
            )

    return chatbot, secret_key


async def list_chatbots(
    org_id: UUID, *, status: ChatbotStatus | None, limit: int, offset: int
) -> tuple[list[Chatbot], int]:
    async with tenant_session(org_id, readonly=True) as session:
        repo = ChatbotRepository(session)
        items = await repo.list_for_org(org_id, status=status, limit=limit, offset=offset)
        total = await repo.count(org_id=org_id)
    return items, total


async def get_chatbot(org_id: UUID, chatbot_id: UUID) -> Chatbot:
    async with tenant_session(org_id, readonly=True) as session:
        chatbot = await ChatbotRepository(session).get_for_org(chatbot_id, org_id)
    if chatbot is None:
        raise NotFoundError(f"Chatbot {chatbot_id} not found")
    return chatbot


async def update_chatbot(org_id: UUID, chatbot_id: UUID, payload: ChatbotUpdate) -> Chatbot:
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)

    # `exclude_none` is what makes this a partial patch, and it is right for every field
    # whose null means "leave it alone". `retention_days` is the exception: null there is the
    # value meaning "keep transcripts forever", and dropping it would make retention a
    # one-way switch a tenant could never turn back off. Only a field the caller actually
    # named is reinstated, so an omitted one still means no change.
    named = payload.model_dump(exclude_unset=True)
    if "retention_days" in named:
        updates["retention_days"] = named["retention_days"]

    async with tenant_session(org_id) as session:
        repo = ChatbotRepository(session)
        chatbot = await repo.get_for_org(chatbot_id, org_id)
        if chatbot is None:
            raise NotFoundError(f"Chatbot {chatbot_id} not found")

        if "model_config_json" in updates:
            updates["model_config_json"] = payload.model_config_json.model_dump()
        if payload.theme_json is not None:
            # An explicit `{}` is how a tenant goes back to the default look, so this is
            # a replacement rather than a merge.
            updates["theme_json"] = payload.theme_json.model_dump(exclude_none=True)
        for field, value in updates.items():
            setattr(chatbot, field, value)
        session.add(chatbot)
        public_key = chatbot.public_key

    # Config is cached on the widget read path, so an update must evict it immediately
    # rather than waiting out the TTL.
    await _cache().invalidate(public_key)
    return chatbot


async def rotate_secret(org_id: UUID, chatbot_id: UUID) -> str:
    secret_key = generate_secret_key(settings.environment)
    async with tenant_session(org_id) as session:
        chatbot = await ChatbotRepository(session).get_for_org(chatbot_id, org_id)
        if chatbot is None:
            raise NotFoundError(f"Chatbot {chatbot_id} not found")
        chatbot.secret_key_hash = hash_api_key(secret_key)
        session.add(chatbot)
    return secret_key


async def delete_chatbot(org_id: UUID, chatbot_id: UUID) -> None:
    async with tenant_session(org_id) as session:
        repo = ChatbotRepository(session)
        chatbot = await repo.get_for_org(chatbot_id, org_id)
        if chatbot is None:
            raise NotFoundError(f"Chatbot {chatbot_id} not found")
        public_key = chatbot.public_key
        # Documents, chunks, conversations and messages cascade at the database level.
        await repo.delete(chatbot)

    await _cache().invalidate(public_key)


def build_embed_snippet(chatbot: Chatbot) -> EmbedSnippet:
    """The snippet carries the key and nothing else.

    Where the API lives is deployment detail the loader reads from `config.json` on the widget
    origin, so moving the API never asks a tenant to edit the HTML they pasted.
    """
    loader_url = f"{settings.widget_cdn_base_url.rstrip('/')}/loader.js"
    snippet = f'<script src="{loader_url}" data-chatbot-key="{chatbot.public_key}" async></script>'
    return EmbedSnippet(public_key=chatbot.public_key, loader_url=loader_url, snippet=snippet)
