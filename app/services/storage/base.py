from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from uuid import UUID


def build_storage_key(org_id: UUID, chatbot_id: UUID, document_id: UUID, filename: str) -> str:
    """Tenant-first key layout so a whole org's objects can be listed, lifecycle-ruled or
    deleted with a single prefix operation."""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"org/{org_id}/chatbot/{chatbot_id}/{document_id}.{suffix}"


class ObjectStorage(ABC):
    """Raw uploaded files live here, never in Postgres."""

    @abstractmethod
    async def upload(
        self, key: str, stream: AsyncIterator[bytes], *, content_type: str
    ) -> None: ...

    @abstractmethod
    async def download(self, key: str) -> bytes: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    async def close(self) -> None:
        return None
