import time
from dataclasses import dataclass
from uuid import UUID

from app.core.config import settings
from app.core.exceptions import DocumentProcessingError, NotFoundError
from app.core.logging import get_logger
from app.db.session import tenant_session
from app.models import PARTITIONED_EMBEDDING_DIMENSIONS, DocumentChunk, DocumentStatus
from app.repositories import DocumentChunkRepository, DocumentRepository
from app.services.ai import factory
from app.services.ingestion.chunker import chunk_sections
from app.services.ingestion.extractors import extract_text
from app.services.ingestion.scanner import ensure_clean
from app.services.storage import get_object_storage

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IngestionResult:
    document_id: UUID
    chunk_count: int
    duration_ms: int


async def _set_status(
    org_id: UUID,
    document_id: UUID,
    status: DocumentStatus,
    *,
    error_message: str | None = None,
    chunk_count: int | None = None,
) -> None:
    async with tenant_session(org_id) as session:
        document = await DocumentRepository(session).get(document_id)
        if document is None:
            return
        document.status = status
        document.error_message = error_message[:2000] if error_message else None
        if chunk_count is not None:
            document.chunk_count = chunk_count
        session.add(document)


async def process_document(org_id: UUID, document_id: UUID) -> IngestionResult:
    """Extract, chunk, embed and persist one document.

    Idempotent by design: the chunk rows for `document_id` are replaced wholesale, so a
    retried job produces the same end state instead of duplicating chunks.
    """
    started = time.perf_counter()

    async with tenant_session(org_id) as session:
        document = await DocumentRepository(session).get(document_id)
        if document is None:
            raise NotFoundError(f"Document {document_id} not found")
        storage_path = document.storage_path
        file_type = document.file_type
        chatbot_id = document.chatbot_id
        filename = document.filename

    await _set_status(org_id, document_id, DocumentStatus.PROCESSING)

    log = logger.bind(document_id=str(document_id), chatbot_id=str(chatbot_id))

    payload = await get_object_storage().download(storage_path)
    # Before any extractor touches it. `pypdf` and `python-docx` parse hostile input for a
    # living, so they are the last thing that should see an unscanned file.
    await ensure_clean(payload, filename=filename)

    sections = extract_text(file_type, payload)
    chunks = chunk_sections(sections, settings.ingestion)
    if not chunks:
        raise DocumentProcessingError(
            "Document produced no usable chunks after splitting", retryable=False
        )

    log.info("ingestion.chunked", filename=filename, chunks=len(chunks))

    embedder = await factory.get_embedding_provider(org_id, chatbot_id)
    embeddings = await embedder.embed_batch([chunk.content for chunk in chunks])
    dimension = _settle_dimension(embeddings, locked=embedder.dimension, log=log)
    if embedder.dimension is None:
        await factory.record_embedding_dimension(org_id, chatbot_id, dimension)

    async with tenant_session(org_id) as session:
        chunk_repo = DocumentChunkRepository(session)
        removed = await chunk_repo.delete_for_document(document_id)
        if removed:
            log.info("ingestion.replaced_existing_chunks", removed=removed)

        await chunk_repo.add_all(
            [
                DocumentChunk(
                    org_id=org_id,
                    document_id=document_id,
                    chatbot_id=chatbot_id,
                    chunk_index=chunk.index,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    embedding_dim=dimension,
                    embedding=vector,
                    metadata_json=chunk.metadata,
                )
                for chunk, vector in zip(chunks, embeddings, strict=True)
            ]
        )

        document = await DocumentRepository(session).get(document_id)
        if document is not None:
            document.status = DocumentStatus.READY
            document.chunk_count = len(chunks)
            document.error_message = None
            session.add(document)

    duration_ms = int((time.perf_counter() - started) * 1000)
    log.info("ingestion.completed", chunks=len(chunks), duration_ms=duration_ms)
    return IngestionResult(
        document_id=document_id, chunk_count=len(chunks), duration_ms=duration_ms
    )


def _settle_dimension(embeddings: list[list[float]], *, locked: int | None, log) -> int:
    """Agree on one width for this document, and refuse anything that contradicts the lock.

    A provider that has quietly started returning a different width would otherwise write rows
    into a second partition, where every existing query would step straight past them.
    """
    widths = {len(vector) for vector in embeddings}
    if len(widths) != 1:
        raise DocumentProcessingError(
            f"The embedding provider returned vectors of mixed widths ({sorted(widths)})",
            retryable=False,
        )

    dimension = widths.pop()
    if locked is not None and dimension != locked:
        raise DocumentProcessingError(
            f"This chatbot's embeddings are {locked} wide but the provider returned "
            f"{dimension}. Delete its documents before changing embedding model.",
            retryable=False,
        )
    if dimension not in PARTITIONED_EMBEDDING_DIMENSIONS:
        # It still stores and still searches — the DEFAULT partition takes it — but without an
        # HNSW index sized for it, so retrieval falls back to a sequential scan.
        log.warning("ingestion.unpartitioned_embedding_dimension", dimension=dimension)
    return dimension


async def mark_failed(org_id: UUID, document_id: UUID, reason: str) -> None:
    await _set_status(org_id, document_id, DocumentStatus.FAILED, error_message=reason)


async def purge_document_objects(storage_path: str) -> None:
    await get_object_storage().delete(storage_path)
