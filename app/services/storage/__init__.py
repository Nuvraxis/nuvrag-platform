from functools import lru_cache

from app.core.config import settings
from app.services.storage.base import ObjectStorage, build_storage_key


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStorage:
    """Backend-specific imports stay lazy so a deployment only pays for the SDK it uses."""
    backend = settings.storage.backend
    if backend == "azure_blob":
        from app.services.storage.azure_blob import AzureBlobStorage

        return AzureBlobStorage(settings.storage)
    if backend == "s3":
        from app.services.storage.s3 import S3ObjectStorage

        return S3ObjectStorage(settings.storage)

    from app.services.storage.local import LocalObjectStorage

    return LocalObjectStorage(settings.storage.local_root)


async def close_object_storage() -> None:
    if get_object_storage.cache_info().currsize:
        await get_object_storage().close()
        get_object_storage.cache_clear()


__all__ = [
    "ObjectStorage",
    "build_storage_key",
    "close_object_storage",
    "get_object_storage",
]
