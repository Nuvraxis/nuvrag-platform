from collections.abc import AsyncIterator

import aioboto3
from botocore.exceptions import ClientError

from app.core.config import StorageSettings
from app.core.exceptions import NotFoundError, UpstreamServiceError
from app.services.storage.base import ObjectStorage


class S3ObjectStorage(ObjectStorage):
    """Works against AWS S3 and any S3-compatible endpoint (MinIO, Ceph, R2)."""

    def __init__(self, config: StorageSettings) -> None:
        self._bucket = config.container
        self._session = aioboto3.Session(
            aws_access_key_id=config.s3_access_key_id,
            aws_secret_access_key=config.s3_secret_access_key,
            region_name=config.s3_region,
        )
        self._client_kwargs = {"endpoint_url": config.s3_endpoint_url}
        self._bucket_ready = False

    def _client(self):
        return self._session.client("s3", **self._client_kwargs)

    async def _ensure_bucket(self, client) -> None:
        """Create the bucket on first write, matching the Azure backend's behaviour.

        Managed buckets are normally provisioned by infrastructure code; this keeps a fresh
        MinIO or a new environment from failing the very first upload.
        """
        if self._bucket_ready:
            return
        try:
            await client.head_bucket(Bucket=self._bucket)
        except ClientError:
            try:
                await client.create_bucket(Bucket=self._bucket)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                    raise UpstreamServiceError(
                        f"S3 bucket {self._bucket!r} unavailable: {exc}"
                    ) from exc
        self._bucket_ready = True

    async def upload(self, key: str, stream: AsyncIterator[bytes], *, content_type: str) -> None:
        # boto3 wants a file-like object, so the stream is materialised here. Uploads are
        # already capped by INGESTION_MAX_UPLOAD_BYTES, which bounds the memory cost.
        body = bytearray()
        async for chunk in stream:
            body.extend(chunk)
        try:
            async with self._client() as client:
                await self._ensure_bucket(client)
                await client.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=bytes(body),
                    ContentType=content_type,
                )
        except ClientError as exc:
            raise UpstreamServiceError(f"S3 upload failed for {key}: {exc}") from exc

    async def download(self, key: str) -> bytes:
        try:
            async with self._client() as client:
                response = await client.get_object(Bucket=self._bucket, Key=key)
                return await response["Body"].read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                raise NotFoundError(f"Object not found: {key}") from exc
            raise UpstreamServiceError(f"S3 download failed for {key}: {exc}") from exc

    async def delete(self, key: str) -> None:
        async with self._client() as client:
            await client.delete_object(Bucket=self._bucket, Key=key)

    async def exists(self, key: str) -> bool:
        try:
            async with self._client() as client:
                await client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False
