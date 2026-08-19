from collections.abc import AsyncIterator

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import ContentSettings
from azure.storage.blob.aio import BlobServiceClient

from app.core.config import StorageSettings
from app.core.exceptions import NotFoundError, UpstreamServiceError
from app.services.storage.base import ObjectStorage


class AzureBlobStorage(ObjectStorage):
    def __init__(self, config: StorageSettings) -> None:
        if config.azure_connection_string:
            self._client = BlobServiceClient.from_connection_string(config.azure_connection_string)
        elif config.azure_account_url:
            # Managed identity via the Secrets Store CSI driver is preferred over a
            # connection string in production.
            from azure.identity.aio import DefaultAzureCredential

            self._client = BlobServiceClient(
                account_url=config.azure_account_url, credential=DefaultAzureCredential()
            )
        else:
            raise ValueError(
                "Azure blob storage needs STORAGE_AZURE_CONNECTION_STRING or "
                "STORAGE_AZURE_ACCOUNT_URL"
            )
        self._container = config.container
        self._container_ready = False

    async def _ensure_container(self) -> None:
        if self._container_ready:
            return
        try:
            await self._client.create_container(self._container)
        except ResourceExistsError:
            pass
        except Exception as exc:
            raise UpstreamServiceError(f"Blob container unavailable: {exc}") from exc
        self._container_ready = True

    async def upload(self, key: str, stream: AsyncIterator[bytes], *, content_type: str) -> None:
        await self._ensure_container()
        blob = self._client.get_blob_client(self._container, key)
        try:
            await blob.upload_blob(
                stream,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type),
            )
        except Exception as exc:
            raise UpstreamServiceError(f"Blob upload failed for {key}: {exc}") from exc

    async def download(self, key: str) -> bytes:
        blob = self._client.get_blob_client(self._container, key)
        try:
            downloader = await blob.download_blob()
            return await downloader.readall()
        except ResourceNotFoundError as exc:
            raise NotFoundError(f"Object not found: {key}") from exc
        except Exception as exc:
            raise UpstreamServiceError(f"Blob download failed for {key}: {exc}") from exc

    async def delete(self, key: str) -> None:
        blob = self._client.get_blob_client(self._container, key)
        try:
            await blob.delete_blob()
        except ResourceNotFoundError:
            return

    async def exists(self, key: str) -> bool:
        blob = self._client.get_blob_client(self._container, key)
        return await blob.exists()

    async def close(self) -> None:
        await self._client.close()
