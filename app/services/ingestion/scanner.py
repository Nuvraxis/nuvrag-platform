"""Malware scanning via clamd's INSTREAM command.

Speaking the wire protocol directly rather than pulling in a client library: it is a few
dozen lines, and every published async client either wraps a blocking socket or is
unmaintained — neither is worth a dependency in the ingestion hot path.

Scanning happens on the worker, after the file is fetched from object storage and before any
extractor parses it. That ordering is the point: the parsers (`pypdf`, `python-docx`) are the
attack surface, so nothing hostile should reach them.
"""

import asyncio
import struct
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol

from app.core.config import IngestionSettings, settings
from app.core.exceptions import DocumentProcessingError
from app.core.logging import get_logger

logger = get_logger(__name__)

_INSTREAM = b"zINSTREAM\0"
_END_OF_STREAM = struct.pack("!L", 0)
_RESPONSE_LIMIT = 4096


@dataclass(frozen=True, slots=True)
class ScanResult:
    clean: bool
    signature: str | None = None


class MalwareScanner(Protocol):
    async def scan(self, payload: bytes) -> ScanResult: ...


class DisabledScanner:
    """Used when no clamd host is configured.

    Reports every payload as clean rather than raising, so a deployment that has consciously
    not enabled scanning still ingests. The decision is visible in configuration, not buried
    in a silent exception handler.
    """

    async def scan(self, payload: bytes) -> ScanResult:
        return ScanResult(clean=True)


class ClamAVScanner:
    def __init__(self, host: str, port: int, *, timeout: float, chunk_size: int) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._chunk_size = chunk_size

    async def scan(self, payload: bytes) -> ScanResult:
        try:
            raw = await asyncio.wait_for(self._exchange(payload), timeout=self._timeout)
        except TimeoutError as exc:
            raise DocumentProcessingError("Malware scan timed out", retryable=True) from exc
        except OSError as exc:
            # Connection refused, DNS failure, reset mid-stream. The file is unscanned, so
            # the job is retried rather than allowed through.
            raise DocumentProcessingError(
                f"Malware scanner is unreachable: {exc}", retryable=True
            ) from exc

        return _interpret(raw)

    async def _exchange(self, payload: bytes) -> str:
        reader, writer = await asyncio.open_connection(self._host, self._port)
        try:
            writer.write(_INSTREAM)
            for start in range(0, len(payload), self._chunk_size):
                chunk = payload[start : start + self._chunk_size]
                writer.write(struct.pack("!L", len(chunk)) + chunk)
                await writer.drain()

            writer.write(_END_OF_STREAM)
            await writer.drain()

            response = await reader.read(_RESPONSE_LIMIT)
            return response.decode("utf-8", errors="replace").strip().strip("\0")
        finally:
            writer.close()
            # A close that fails has nothing left to affect — the verdict is already read.
            with suppress(OSError):
                await writer.wait_closed()


def _interpret(response: str) -> ScanResult:
    """clamd answers `stream: OK`, `stream: <Signature> FOUND`, or `... ERROR`."""
    if response.endswith("OK"):
        return ScanResult(clean=True)

    if response.endswith("FOUND"):
        _, _, tail = response.partition(":")
        signature = tail.strip().removesuffix("FOUND").strip() or "unknown"
        return ScanResult(clean=False, signature=signature)

    # `INSTREAM size limit exceeded`, `Can't allocate memory`, and friends. Not a verdict,
    # so it must not be read as one.
    raise DocumentProcessingError(f"Malware scan failed: {response}", retryable=True)


def build_scanner(config: IngestionSettings) -> MalwareScanner:
    if not config.clamav_host:
        return DisabledScanner()
    return ClamAVScanner(
        config.clamav_host,
        config.clamav_port,
        timeout=config.clamav_timeout_seconds,
        chunk_size=config.clamav_chunk_bytes,
    )


_scanner: MalwareScanner | None = None


def get_scanner() -> MalwareScanner:
    global _scanner
    if _scanner is None:
        _scanner = build_scanner(settings.ingestion)
    return _scanner


async def ensure_clean(payload: bytes, *, filename: str) -> None:
    """Raises if the payload is infected; returns quietly if it is clean or unscanned."""
    result = await get_scanner().scan(payload)
    if result.clean:
        return

    logger.warning("ingestion.malware_detected", filename=filename, signature=result.signature)
    raise DocumentProcessingError(
        f"Malware detected ({result.signature}); the file was not indexed", retryable=False
    )
