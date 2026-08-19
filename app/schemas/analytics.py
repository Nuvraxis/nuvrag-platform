from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentTotals(BaseModel):
    """Counts per ingestion status, always with every status present so the dashboard does
    not have to guess whether a missing key means zero or means "not measured"."""

    pending: int = 0
    processing: int = 0
    ready: int = 0
    failed: int = 0
    total: int = 0
    chunks: int = 0


class MessageTotals(BaseModel):
    user: int = 0
    assistant: int = 0
    total: int = 0
    average_latency_ms: int | None = None


class DailyActivityPoint(BaseModel):
    day: date
    conversations: int
    messages: int


class ChatbotAnalytics(BaseModel):
    chatbot_id: UUID
    window_days: int = Field(description="Length of the daily series, ending today (UTC)")
    documents: DocumentTotals
    conversations: int
    messages: MessageTotals
    daily: list[DailyActivityPoint]
