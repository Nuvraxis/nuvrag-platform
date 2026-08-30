import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import (
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
    UsageCapExceededError,
)
from app.core.logging import get_logger
from app.db.session import tenant_session
from app.models import Document, DocumentStatus, FileType
from app.repositories import DocumentRepository
from app.services.ai import factory
from app.services.storage import build_storage_key, get_object_storage
from app.services.usage import UsageKind, consume, headroom, ingestion_units

logger = get_logger(__name__)

_EXTENSION_TO_TYPE = {
    "pdf": FileType.PDF,
    "docx": FileType.DOCX,
    "md": FileType.MD,
    "markdown": FileType.MD,
    "mdx": FileType.MDX,
    "txt": FileType.TXT,
    "text": FileType.TXT,
}

# `text/mdx` is not registered with IANA and browsers send whatever they feel like for it —
# usually nothing, occasionally the markdown or plain-text types.
_MARKDOWN_CONTENT_TYPES = {"text/markdown", "text/x-markdown", "text/mdx", "text/plain"}

_ALLOWED_CONTENT_TYPES = {
    FileType.PDF: {"application/pdf", "application/x-pdf"},
    FileType.DOCX: {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
    },
    FileType.MD: _MARKDOWN_CONTENT_TYPES,
    FileType.MDX: _MARKDOWN_CONTENT_TYPES,
    FileType.TXT: {"text/plain"},
}

# Browsers are inconsistent about content types for text formats, so binary formats are
# additionally checked against their magic bytes.
_MAGIC_PREFIXES = {
    FileType.PDF: b"%PDF-",
    FileType.DOCX: b"PK\x03\x04",
}

_GENERIC_CONTENT_TYPES = {"application/octet-stream", "binary/octet-stream", ""}


@dataclass(slots=True)
class UploadOutcome:
    document: Document
    task_id: str | None


def _resolve_file_type(filename: str, content_type: str) -> FileType:
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    file_type = _EXTENSION_TO_TYPE.get(extension)
    if file_type is None:
        supported = ", ".join(sorted({f".{key}" for key in _EXTENSION_TO_TYPE}))
        raise UnsupportedMediaTypeError(
            f"Unsupported file extension {extension!r}. Supported types: {supported}"
        )

    declared = (content_type or "").split(";")[0].strip().lower()
    if declared not in _GENERIC_CONTENT_TYPES and declared not in _ALLOWED_CONTENT_TYPES[file_type]:
        raise UnsupportedMediaTypeError(
            f"Content type {declared!r} does not match a {file_type} document"
        )
    return file_type


class _MeteredStream:
    """Streams the upload straight through to object storage.

    Nothing larger than one chunk is held in memory, and the size cap is enforced mid-flight
    so an oversized file is rejected before it is fully transferred.
    """

    def __init__(self, upload: UploadFile, file_type: FileType, max_bytes: int) -> None:
        self._upload = upload
        self._file_type = file_type
        self._max_bytes = max_bytes
        self._chunk_size = settings.ingestion.upload_stream_chunk_bytes
        self.size = 0
        self.digest = hashlib.sha256()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        first = True
        while chunk := await self._upload.read(self._chunk_size):
            if first:
                self._verify_magic(chunk)
                first = False
            self.size += len(chunk)
            if self.size > self._max_bytes:
                raise PayloadTooLargeError(
                    f"File exceeds the {self._max_bytes // (1024 * 1024)} MB upload limit"
                )
            self.digest.update(chunk)
            yield chunk

        if self.size == 0:
            raise UnsupportedMediaTypeError("Uploaded file is empty")

    def _verify_magic(self, head: bytes) -> None:
        expected = _MAGIC_PREFIXES.get(self._file_type)
        if expected and not head.startswith(expected):
            raise UnsupportedMediaTypeError(
                f"File contents do not look like a valid {self._file_type} document"
            )


async def upload_document(
    *,
    org_id: UUID,
    chatbot_id: UUID,
    uploaded_by: UUID,
    upload: UploadFile,
    cap_units: int | None = None,
) -> UploadOutcome:
    """Validate, stream to object storage, record the document, then hand off to the worker.

    Returns as soon as the job is queued; the caller polls the document for status.
    """
    filename = (upload.filename or "document").strip()[:512]
    file_type = _resolve_file_type(filename, upload.content_type or "")

    # Checked after the request itself is judged, so a bad file still reports what is wrong
    # with it, but before a byte is streamed anywhere: accepting an upload no worker could
    # embed costs the tenant the transfer and hands them a `failed` document minutes later.
    await factory.require_embedding_ready(org_id, chatbot_id)

    # First of two cap checks, and the cheap one. What an upload actually costs is not known
    # until it has been streamed — the unit is derived from `size_bytes`, which `_MeteredStream`
    # only knows once it has read the file — so a chatbot that is *already* at its ceiling is
    # turned away here, before a byte moves. The exact charge is settled below.
    allowance = await headroom(org_id, chatbot_id, kind=UsageKind.INGESTION, cap=cap_units)
    if not allowance.allowed:
        raise UsageCapExceededError(
            "This chatbot has reached its monthly ingestion limit. It resets at the start of "
            "next month, or an administrator can raise the limit.",
            kind=str(UsageKind.INGESTION),
            used=allowance.used,
            cap=allowance.cap,
        )

    document_id = uuid4()
    storage_key = build_storage_key(org_id, chatbot_id, document_id, filename)
    stream = _MeteredStream(upload, file_type, settings.ingestion.max_upload_bytes)
    storage = get_object_storage()

    try:
        await storage.upload(
            storage_key, stream.__aiter__(), content_type=upload.content_type or ""
        )
    except PayloadTooLargeError, UnsupportedMediaTypeError:
        await storage.delete(storage_key)
        raise

    units = ingestion_units(stream.size)

    # Second check, with the real cost. An upload that started under the cap can carry it past
    # by at most one document — bounded by `INGESTION_MAX_UPLOAD_BYTES` — because its size was
    # unknowable beforehand. Charged before the row is written, so a refusal leaves nothing
    # behind but the object this deletes.
    spend = await consume(org_id, chatbot_id, kind=UsageKind.INGESTION, amount=units, cap=cap_units)
    if not spend.allowed:
        await storage.delete(storage_key)
        raise UsageCapExceededError(
            "This document would take the chatbot past its monthly ingestion limit. It resets "
            "at the start of next month, or an administrator can raise the limit.",
            kind=str(UsageKind.INGESTION),
            used=spend.used,
            cap=spend.cap,
        )

    async with tenant_session(org_id) as session:
        document = await DocumentRepository(session).add(
            Document(
                id=document_id,
                org_id=org_id,
                chatbot_id=chatbot_id,
                filename=filename,
                file_type=file_type,
                content_type=upload.content_type or "application/octet-stream",
                storage_path=storage_key,
                checksum_sha256=stream.digest.hexdigest(),
                size_bytes=stream.size,
                status=DocumentStatus.PENDING,
                uploaded_by=uploaded_by,
            )
        )

    task_id = _enqueue_ingestion(org_id, document_id)
    logger.info(
        "document.uploaded",
        document_id=str(document_id),
        chatbot_id=str(chatbot_id),
        size_bytes=stream.size,
        ingestion_units=units,
        task_id=task_id,
    )
    return UploadOutcome(document=document, task_id=task_id)


def _enqueue_ingestion(org_id: UUID, document_id: UUID) -> str | None:
    from app.worker.tasks import process_document_task

    try:
        # `task_id` is derived from the document so a duplicate enqueue collapses onto the
        # same job rather than processing the file twice.
        async_result = process_document_task.apply_async(
            args=[str(org_id), str(document_id)], task_id=f"ingest-{document_id}"
        )
        return async_result.id
    except Exception as exc:  # noqa: BLE001 - broker outage must not lose the upload
        logger.error("document.enqueue_failed", document_id=str(document_id), error=str(exc))
        return None


async def list_documents(
    org_id: UUID,
    chatbot_id: UUID,
    *,
    status: DocumentStatus | None,
    limit: int,
    offset: int,
) -> tuple[list[Document], int]:
    async with tenant_session(org_id, readonly=True) as session:
        repo = DocumentRepository(session)
        items = await repo.list_for_chatbot(chatbot_id, status=status, limit=limit, offset=offset)
        total = await repo.count(chatbot_id=chatbot_id)
    return items, total


async def get_document(org_id: UUID, chatbot_id: UUID, document_id: UUID) -> Document:
    async with tenant_session(org_id, readonly=True) as session:
        document = await DocumentRepository(session).get_for_chatbot(document_id, chatbot_id)
    if document is None:
        raise NotFoundError(f"Document {document_id} not found")
    return document


async def delete_document(org_id: UUID, chatbot_id: UUID, document_id: UUID) -> None:
    async with tenant_session(org_id) as session:
        repo = DocumentRepository(session)
        document = await repo.get_for_chatbot(document_id, chatbot_id)
        if document is None:
            raise NotFoundError(f"Document {document_id} not found")
        storage_path = document.storage_path
        # Chunks cascade with the document row.
        await repo.delete(document)

    _enqueue_object_purge(storage_path)


async def reprocess_document(org_id: UUID, chatbot_id: UUID, document_id: UUID) -> str | None:
    """Re-run ingestion for a document that failed or predates a chunking change."""
    async with tenant_session(org_id) as session:
        document = await DocumentRepository(session).get_for_chatbot(document_id, chatbot_id)
        if document is None:
            raise NotFoundError(f"Document {document_id} not found")
        document.status = DocumentStatus.PENDING
        document.error_message = None
        session.add(document)

    return _enqueue_ingestion(org_id, document_id)


def _enqueue_object_purge(storage_path: str) -> None:
    from app.worker.tasks import purge_document_objects_task

    try:
        purge_document_objects_task.apply_async(args=[storage_path])
    except Exception as exc:  # noqa: BLE001 - orphaned blobs are swept separately
        logger.error("document.purge_enqueue_failed", path=storage_path, error=str(exc))
