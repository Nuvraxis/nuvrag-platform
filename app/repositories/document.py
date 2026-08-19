from dataclasses import dataclass
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import cast, delete, text
from sqlmodel import select

from app.models import Document, DocumentChunk, DocumentStatus
from app.repositories.base import BaseRepository


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk: DocumentChunk
    similarity: float


class DocumentRepository(BaseRepository[Document]):
    model = Document

    async def get_for_chatbot(self, document_id: UUID, chatbot_id: UUID) -> Document | None:
        result = await self.session.execute(
            select(Document).where(Document.id == document_id, Document.chatbot_id == chatbot_id)
        )
        return result.scalar_one_or_none()

    async def list_for_chatbot(
        self,
        chatbot_id: UUID,
        *,
        status: DocumentStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Document]:
        stmt = select(Document).where(Document.chatbot_id == chatbot_id)
        if status is not None:
            stmt = stmt.where(Document.status == status)
        stmt = stmt.order_by(Document.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def find_duplicate(self, chatbot_id: UUID, checksum: str) -> Document | None:
        result = await self.session.execute(
            select(Document)
            .where(
                Document.chatbot_id == chatbot_id,
                Document.checksum_sha256 == checksum,
                Document.status != DocumentStatus.FAILED,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()


class DocumentChunkRepository(BaseRepository[DocumentChunk]):
    model = DocumentChunk

    async def delete_for_document(self, document_id: UUID) -> int:
        """Makes re-processing idempotent: a retried job replaces its chunks rather than
        appending a second copy."""
        result = await self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        return int(result.rowcount or 0)

    async def search(
        self,
        *,
        chatbot_id: UUID,
        embedding: list[float],
        dimension: int,
        top_k: int,
        min_similarity: float,
        ef_search: int | None = None,
    ) -> list[RetrievedChunk]:
        """Cosine similarity search pre-filtered by chatbot and embedding width.

        Both filters are load-bearing. The chatbot keeps the search off another tenant's rows;
        the width prunes to a single partition, and without it the scan would reach vectors of
        other lengths, which Postgres rejects outright rather than ranking badly.

        The similarity threshold is applied after the index scan rather than as a WHERE clause
        so the HNSW index still drives the ordering.
        """
        if ef_search is not None:
            await self.session.execute(text(f"SET LOCAL hnsw.ef_search = {int(ef_search)}"))

        # The cast is what makes the partition's HNSW index usable: its column has no declared
        # width, so the index is built over `embedding::vector(N)` and only a query spelled the
        # same way matches it.
        vector = cast(DocumentChunk.embedding, Vector(dimension))
        distance = vector.cosine_distance(embedding).label("distance")
        stmt = (
            select(DocumentChunk, distance)
            .where(
                DocumentChunk.chatbot_id == chatbot_id,
                DocumentChunk.embedding_dim == dimension,
            )
            .order_by(distance)
            .limit(top_k)
        )
        result = await self.session.execute(stmt)

        matches: list[RetrievedChunk] = []
        for chunk, raw_distance in result.all():
            similarity = 1.0 - float(raw_distance)
            if similarity >= min_similarity:
                matches.append(RetrievedChunk(chunk=chunk, similarity=similarity))
        return matches
