from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import cast, delete, exists, update
from sqlmodel import func, select

from app.core.security import utcnow
from app.models import Conversation, MemoryEntry, Ticket
from app.repositories.base import BaseRepository
from app.repositories.conversation import UNRESOLVED_TICKET_STATUSES

# How stale a note has to be before a retrieval bothers to refresh it. `last_referenced_at`
# is itself indexed, so changing it cannot be a HOT update: every bump writes a new tuple
# version and re-inserts the row's vector into the HNSW index. Refreshing on literally every
# turn would therefore rewrite a visitor's whole working set several times a conversation, to
# move a timestamp the sweep only ever reads in days.
TOUCH_STALENESS = timedelta(hours=1)


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

    async def search(
        self,
        *,
        chatbot_id: UUID,
        subject_id: str,
        embedding: list[float],
        top_k: int,
        min_similarity: float,
        dimension: int,
    ) -> list[RetrievedMemory]:
        """The closest few things known about one visitor.

        Deliberately no `hnsw.ef_search` and no reliance on the HNSW index, unlike the
        document search. `subject_id` narrows the scan to one person's couple of hundred rows
        before any ordering happens, and sorting that by distance is cheaper than asking an
        approximate index to rank a whole partition and then discarding almost all of it. The
        HNSW index still exists per partition, and the planner is free to change its mind on
        data this code has not seen — the EXPLAIN is in the iteration notes.

        The threshold is applied after ordering rather than as a WHERE clause, matching the
        document search so that both read the same way.
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
            .limit(top_k)
        )

        found: list[RetrievedMemory] = []
        for entry, raw_distance in result.all():
            similarity = 1.0 - float(raw_distance)
            if similarity >= min_similarity:
                found.append(RetrievedMemory(entry=entry, similarity=similarity))
        return found

    async def touch(self, entries: Sequence[MemoryEntry]) -> int:
        """Mark entries as still in use, which is what keeps them out of the sweep.

        Every retrieved entry shares one width — the search filters on it — so naming it here
        prunes the update to a single partition instead of every one of them.

        The staleness predicate is what makes this cheap rather than merely correct. See
        `TOUCH_STALENESS`: a bump is an HNSW re-insert, so a visitor's second question of the
        same minute updates nothing at all, and the timestamp is still accurate to far finer
        than the days the sweep measures in.
        """
        if not entries:
            return 0
        now = utcnow()
        result = await self.session.execute(
            update(MemoryEntry)
            .where(
                MemoryEntry.embedding_dim == entries[0].embedding_dim,
                MemoryEntry.id.in_([entry.id for entry in entries]),
                MemoryEntry.last_referenced_at < now - TOUCH_STALENESS,
            )
            .values(last_referenced_at=now)
        )
        return int(result.rowcount or 0)

    async def list_for_subject(
        self, chatbot_id: UUID, subject_id: str, *, limit: int
    ) -> list[MemoryEntry]:
        """Everything known about one visitor, newest first.

        Not `search` with a neutral vector: the dashboard panel has no question to be relevant
        to, so ranking by distance would order a person's history by an accident of whatever
        vector was passed in. Newest first is the order a human reads a history in.
        """
        result = await self.session.execute(
            select(MemoryEntry)
            .where(MemoryEntry.chatbot_id == chatbot_id, MemoryEntry.subject_id == subject_id)
            .order_by(MemoryEntry.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def delete_for_subject(self, chatbot_id: UUID, subject_id: str) -> int:
        """Every note about one visitor on one chatbot. The erasure primitive.

        Deliberately unconditional. It ignores the open-ticket pin the sweep respects, for the
        same reason `delete_conversation` ignores it: somebody has asked for this specific
        person to be forgotten, and an erasure request that quietly did nothing because a
        ticket happened to be open would be worse than useless.
        """
        result = await self.session.execute(
            delete(MemoryEntry).where(
                MemoryEntry.chatbot_id == chatbot_id, MemoryEntry.subject_id == subject_id
            )
        )
        return int(result.rowcount or 0)

    async def expired_ids(self, chatbot_id: UUID, *, cutoff: datetime, limit: int) -> list[UUID]:
        """Notes unused since `cutoff` that no unresolved ticket is holding open.

        `last_referenced_at` rather than `created_at`: a note the assistant is still using has
        not gone stale just because it was learned a while ago, which is the same reasoning
        that ages a conversation on `updated_at`.

        The pin extends the rule conversations already have. Losing what is known about a
        visitor while staff are actively working their open ticket would be a worse failure
        than keeping it a little longer, so an open or pending ticket anywhere in that
        subject's history holds all of their notes. Resolving or closing it releases the pin.

        The join is on `(chatbot_id, external_session_id)` because that pair is what a subject
        *is*: the same session id on another chatbot is another person's business.
        """
        pinned = (
            select(Ticket.id)
            .join(Conversation, Conversation.id == Ticket.conversation_id)
            .where(
                Conversation.chatbot_id == MemoryEntry.chatbot_id,
                Conversation.external_session_id == MemoryEntry.subject_id,
                Ticket.status.in_(UNRESOLVED_TICKET_STATUSES),
            )
        )
        result = await self.session.execute(
            select(MemoryEntry.id)
            .where(MemoryEntry.chatbot_id == chatbot_id)
            .where(MemoryEntry.last_referenced_at < cutoff)
            .where(~exists(pinned))
            .order_by(MemoryEntry.last_referenced_at)
            .limit(limit)
        )
        return list(result.scalars())

    async def delete_by_ids(self, entry_ids: Sequence[UUID]) -> int:
        if not entry_ids:
            return 0
        result = await self.session.execute(
            delete(MemoryEntry).where(MemoryEntry.id.in_(entry_ids))
        )
        return int(result.rowcount or 0)
