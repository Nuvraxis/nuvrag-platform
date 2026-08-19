from uuid import UUID

from sqlmodel import select

from app.models import ChatbotAIConfig
from app.repositories.base import BaseRepository


class ChatbotAIConfigRepository(BaseRepository[ChatbotAIConfig]):
    model = ChatbotAIConfig

    async def get_for_chatbot(self, chatbot_id: UUID) -> ChatbotAIConfig | None:
        result = await self.session.execute(
            select(ChatbotAIConfig).where(ChatbotAIConfig.chatbot_id == chatbot_id)
        )
        return result.scalar_one_or_none()
