import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import aiofiles

from app.core.exceptions import NotFoundError
from app.services.storage.base import ObjectStorage


class LocalObjectStorage(ObjectStorage):
    """Filesystem-backed storage for local development and tests.

    Not suitable for multi-replica deployments — the API and worker pods would each see a
    different filesystem. Use the Azure or S3 backend anywhere beyond a single machine.
    """

    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        candidate = (self._root / key).resolve()
        if not candidate.is_relative_to(self._root):
            raise ValueError(f"Storage key escapes the storage root: {key!r}")
        return candidate

    async def upload(self, key: str, stream: AsyncIterator[bytes], *, content_type: str) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "wb") as handle:
            async for chunk in stream:
                await handle.write(chunk)

    async def download(self, key: str) -> bytes:
        path = self._path_for(key)
        if not path.exists():
            raise NotFoundError(f"Object not found: {key}")
        async with aiofiles.open(path, "rb") as handle:
            return await handle.read()

    async def delete(self, key: str) -> None:
        path = self._path_for(key)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()

    async def exists(self, key: str) -> bool:
        return self._path_for(key).exists()
