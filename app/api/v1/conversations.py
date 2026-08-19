from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentPrincipal, OwnedChatbot, Pagination, RequireAdmin
from app.core.exceptions import NotFoundError
from app.db.session import tenant_session
from app.repositories import ConversationRepository, MessageRepository
from app.schemas.chat import ConversationRead, MessageRead
from app.schemas.common import Page
from app.services import conversation as conversation_service

router = APIRouter(prefix="/chatbots/{chatbot_id}/conversations", tags=["conversations"])


@router.get("", response_model=Page[ConversationRead])
async def list_conversations(
    chatbot: OwnedChatbot, principal: CurrentPrincipal, page: Pagination
) -> Page[ConversationRead]:
    async with tenant_session(principal.org_id, readonly=True) as session:
        repo = ConversationRepository(session)
        items = await repo.list_for_chatbot(chatbot.id, limit=page.limit, offset=page.offset)
        total = await repo.count(chatbot_id=chatbot.id)

    return Page(
        items=[ConversationRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{conversation_id}/messages", response_model=Page[MessageRead])
async def list_messages(
    chatbot: OwnedChatbot,
    principal: CurrentPrincipal,
    conversation_id: UUID,
    page: Pagination,
) -> Page[MessageRead]:
    async with tenant_session(principal.org_id, readonly=True) as session:
        conversation = await ConversationRepository(session).get(conversation_id)
        if conversation is None or conversation.chatbot_id != chatbot.id:
            raise NotFoundError(f"Conversation {conversation_id} not found")

        message_repo = MessageRepository(session)
        items = await message_repo.list_for_conversation(
            conversation_id, limit=page.limit, offset=page.offset
        )
        total = await message_repo.count(conversation_id=conversation_id)

    return Page(
        items=[MessageRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one conversation and its messages",
)
async def delete_conversation(
    chatbot: OwnedChatbot, principal: RequireAdmin, conversation_id: UUID
) -> None:
    """Irreversible, and the way a single erasure request is honoured without waiting for
    the retention sweep. Admin or above, matching document deletion — a transcript is the
    tenant's record of what their visitors asked."""
    await conversation_service.delete_conversation(principal.org_id, chatbot.id, conversation_id)
