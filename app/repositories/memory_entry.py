from dataclasses import dataclass
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import cast
from sqlmodel import func, select

from app.models import MemoryEntry
from app.repositories.base import BaseRepository


@dataclass(frozen=True, slots=True)
class RetrievedMemory:
    entry: MemoryEntry
    similarity: float


class MemoryEntryRepository(BaseRepository[MemoryEntry]):
    model = MemoryEntry

    async def count_for_subject(self, chatbot_id: UUID, subject_id: str) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(MemoryEntry)
            .where(MemoryEntry.chatbot_id == chatbot_id, MemoryEntry.subject_id == subject_id)
        )
        return int(result.scalar_one())

    async def nearest(
        self,
        *,
        chatbot_id: UUID,
        subject_id: str,
        embedding: list[float],
        dimension: int,
    ) -> RetrievedMemory | None:
        """The single closest thing this subject is already known to have said.

        Same three filters as `DocumentChunkRepository.search` and load-bearing for the same
        reasons — the chatbot keeps one tenant's bot out of another's memories, and the width
        prunes to one partition, without which the scan would reach vectors of other lengths
        that Postgres refuses to compare at all. `subject_id` is the third because a memory
        belongs to a person, not to a corpus.

        The cast is what makes the partition's HNSW index usable: the column has no declared
        width, so the index is built over `embedding::vector(N)` and only a query spelled the
        same way can match it.
        """
        vector = cast(MemoryEntry.embedding, Vector(dimension))
        distance = vector.cosine_distance(embedding).label("distance")
        result = await self.session.execute(
            select(MemoryEntry, distance)
            .where(
                MemoryEntry.chatbot_id == chatbot_id,
                MemoryEntry.subject_id == subject_id,
                MemoryEntry.embedding_dim == dimension,
            )
            .order_by(distance)
            .limit(1)
        )
        row = result.first()
        if row is None:
            return None
        entry, raw_distance = row
        return RetrievedMemory(entry=entry, similarity=1.0 - float(raw_distance))
