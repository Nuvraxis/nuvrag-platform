from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models import DocumentStatus, FileType


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    chatbot_id: UUID
    filename: str
    file_type: FileType
    content_type: str
    size_bytes: int
    chunk_count: int
    status: DocumentStatus
    error_message: str | None
    uploaded_by: UUID | None
    created_at: datetime
    updated_at: datetime


class DocumentUploadResponse(BaseModel):
    """Returned immediately; the client polls the document until it reaches `ready`."""

    document: DocumentRead
    task_id: str | None
