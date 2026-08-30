from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentPrincipal, OwnedChatbot, Pagination, RequireAdmin
from app.models import ChatbotStatus
from app.schemas.analytics import ChatbotAnalytics
from app.schemas.chatbot import (
    ChatbotCreate,
    ChatbotCreateResponse,
    ChatbotRead,
    ChatbotSecret,
    ChatbotUpdate,
    EmbedSnippet,
    UsagePeriodRead,
)
from app.schemas.common import Page
from app.services import analytics as analytics_service
from app.services import chatbot as chatbot_service

router = APIRouter(prefix="/chatbots", tags=["chatbots"])


@router.post("", response_model=ChatbotCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_chatbot(payload: ChatbotCreate, principal: RequireAdmin) -> ChatbotCreateResponse:
    chatbot, secret_key = await chatbot_service.create_chatbot(principal.org_id, payload)
    return ChatbotCreateResponse(
        chatbot=ChatbotRead.model_validate(chatbot),
        secret=ChatbotSecret(chatbot_id=chatbot.id, secret_key=secret_key),
    )


@router.get("", response_model=Page[ChatbotRead])
async def list_chatbots(
    principal: CurrentPrincipal,
    page: Pagination,
    status_filter: ChatbotStatus | None = Query(default=None, alias="status"),
) -> Page[ChatbotRead]:
    items, total = await chatbot_service.list_chatbots(
        principal.org_id, status=status_filter, limit=page.limit, offset=page.offset
    )
    return Page(
        items=[ChatbotRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{chatbot_id}", response_model=ChatbotRead)
async def get_chatbot(chatbot: OwnedChatbot, principal: CurrentPrincipal) -> ChatbotRead:
    """The detail view, which is the only place `usage` is populated — the list endpoint
    would need one lookup per row to do the same."""
    usage = await chatbot_service.current_usage(principal.org_id, chatbot.id)
    return ChatbotRead.model_validate(chatbot).model_copy(
        update={"usage": UsagePeriodRead.model_validate(usage) if usage else None}
    )


@router.patch("/{chatbot_id}", response_model=ChatbotRead)
async def update_chatbot(
    chatbot_id: UUID, payload: ChatbotUpdate, principal: RequireAdmin
) -> ChatbotRead:
    updated = await chatbot_service.update_chatbot(principal.org_id, chatbot_id, payload)
    return ChatbotRead.model_validate(updated)


@router.delete("/{chatbot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chatbot(chatbot_id: UUID, principal: RequireAdmin) -> None:
    await chatbot_service.delete_chatbot(principal.org_id, chatbot_id)


@router.post("/{chatbot_id}/rotate-secret", response_model=ChatbotSecret)
async def rotate_secret(chatbot_id: UUID, principal: RequireAdmin) -> ChatbotSecret:
    secret_key = await chatbot_service.rotate_secret(principal.org_id, chatbot_id)
    return ChatbotSecret(chatbot_id=chatbot_id, secret_key=secret_key)


@router.get("/{chatbot_id}/embed-snippet", response_model=EmbedSnippet)
async def embed_snippet(chatbot: OwnedChatbot) -> EmbedSnippet:
    return chatbot_service.build_embed_snippet(chatbot)


@router.get("/{chatbot_id}/analytics", response_model=ChatbotAnalytics)
async def chatbot_analytics(
    chatbot: OwnedChatbot,
    principal: CurrentPrincipal,
    days: int = Query(default=30, ge=1, le=analytics_service.MAX_WINDOW_DAYS),
) -> ChatbotAnalytics:
    """Ingestion and conversation counters for the dashboard overview."""
    return await analytics_service.chatbot_analytics(principal.org_id, chatbot.id, days=days)
