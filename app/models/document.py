from uuid import UUID

from sqlalchemy import BigInteger, Index
from sqlmodel import Field, SQLModel

from app.models.base import (
    OrgScopedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    enum_column,
)
from app.models.enums import DocumentStatus, FileType


class Document(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "document"
    __table_args__ = (
        Index("ix_document_chatbot_id_status", "chatbot_id", "status"),
        Index("ix_document_chatbot_id_created_at", "chatbot_id", "created_at"),
        enum_check("status", DocumentStatus),
        enum_check("file_type", FileType),
    )

    chatbot_id: UUID = Field(
        foreign_key="chatbot.id", ondelete="CASCADE", index=True, nullable=False
    )
    filename: str = Field(max_length=512, nullable=False)
    file_type: FileType = Field(sa_type=enum_column(FileType, name="file_type"), nullable=False)
    content_type: str = Field(max_length=128, nullable=False)
    storage_path: str = Field(max_length=1024, nullable=False)
    checksum_sha256: str | None = Field(default=None, max_length=64, index=True)
    size_bytes: int = Field(sa_type=BigInteger, nullable=False)
    chunk_count: int = Field(default=0, sa_column_kwargs={"server_default": "0"}, nullable=False)
    status: DocumentStatus = Field(
        default=DocumentStatus.PENDING,
        sa_type=enum_column(DocumentStatus, name="status"),
        nullable=False,
    )
    error_message: str | None = Field(default=None, max_length=2000)
    # Kept as a nullable reference so removing a teammate never deletes their uploads.
    uploaded_by: UUID | None = Field(default=None, foreign_key="app_user.id", ondelete="SET NULL")
