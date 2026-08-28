from typing import Any
from uuid import UUID

from celery import Task

from app.core.config import settings
from app.core.exceptions import DocumentProcessingError, NotFoundError
from app.core.logging import get_logger
from app.services.ingestion.pipeline import mark_failed, process_document
from app.worker.celery_app import celery_app
from app.worker.runtime import run as _run

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    name="ingestion.process_document",
    autoretry_for=(),
    max_retries=settings.ingestion.max_task_retries,
    acks_late=True,
)
def process_document_task(self: Task, org_id: str, document_id: str) -> dict[str, Any]:
    """Ingest one uploaded document.

    Keyed by `document_id` and idempotent, so a retry replaces the previous attempt's chunks
    rather than appending to them.
    """
    org_uuid, document_uuid = UUID(org_id), UUID(document_id)
    log = logger.bind(document_id=document_id, org_id=org_id, attempt=self.request.retries + 1)

    try:
        result = _run(process_document(org_uuid, document_uuid))
    except NotFoundError:
        # The document was deleted while queued. Nothing to do, and retrying will not help.
        log.warning("ingestion.document_missing")
        return {"document_id": document_id, "status": "missing"}
    except DocumentProcessingError as exc:
        if not exc.retryable:
            log.warning("ingestion.permanent_failure", reason=exc.message)
            _run(mark_failed(org_uuid, document_uuid, exc.message))
            return {"document_id": document_id, "status": "failed", "reason": exc.message}
        raise self.retry(exc=exc, countdown=_backoff(self.request.retries)) from exc
    except Exception as exc:
        if self.request.retries >= settings.ingestion.max_task_retries:
            reason = f"Ingestion failed after {self.request.retries + 1} attempts: {exc}"
            log.error("ingestion.exhausted_retries", error=str(exc))
            _run(mark_failed(org_uuid, document_uuid, reason))
            # Re-raised so Celery routes the job to the dead-letter queue for inspection.
            raise
        log.warning("ingestion.retrying", error=str(exc))
        raise self.retry(exc=exc, countdown=_backoff(self.request.retries)) from exc

    return {
        "document_id": document_id,
        "status": "ready",
        "chunk_count": result.chunk_count,
        "duration_ms": result.duration_ms,
    }


def _backoff(retries: int) -> int:
    delay = settings.ingestion.retry_backoff_seconds * (2**retries)
    return min(delay, settings.ingestion.retry_backoff_max_seconds)


@celery_app.task(name="maintenance.purge_document_objects")
def purge_document_objects_task(storage_path: str) -> dict[str, str]:
    """Delete the raw file after its document row is gone, so a failed blob delete never
    blocks the user-facing request."""
    from app.services.ingestion.pipeline import purge_document_objects

    _run(purge_document_objects(storage_path))
    return {"storage_path": storage_path, "status": "deleted"}


@celery_app.task(name="maintenance.purge_expired_conversations")
def purge_expired_conversations_task() -> dict[str, Any]:
    """Apply every chatbot's `retention_days`. Scheduled by beat; see `celery_app`.

    Deliberately not retried. The next run is only a day away and re-running a half-finished
    sweep costs another full scan for rows the first pass already deleted, so a transient
    failure is better left to the schedule than to a retry.
    """
    from app.services.conversation import purge_expired_conversations

    report = _run(purge_expired_conversations())
    return {
        "chatbots_considered": report.chatbots_considered,
        "conversations_deleted": report.conversations_deleted,
        "incomplete": report.incomplete,
        "skipped_locked": report.skipped_locked,
    }


@celery_app.task(name="nuvrag_mem.extract_visitor_memory")
def extract_visitor_memory_task(org_id: str, conversation_id: str) -> dict[str, Any]:
    """Write down what the recent turns say about one visitor. Queued after every assistant
    turn on a conversation that already has a ticket.

    Two ids and nothing else: the visitor's session id is a bearer capability, and this
    argument list is a message body that sits in Redis, so the task reads the session id from
    the conversation row under RLS rather than being handed it through the queue.

    Deliberately not retried. Consecutive turns are extracted over overlapping windows, so a
    failed attempt is covered by the next message rather than by a second attempt at this one
    — and paying for another chat completion to recover a fact nobody is waiting for is the
    wrong trade. Upstream failures are already reported as a skip; anything else is a bug and
    is left to surface as a failed task.
    """
    from app.services.nuvrag_mem import extract_visitor_memory

    report = _run(extract_visitor_memory(UUID(org_id), UUID(conversation_id)))
    return {
        "conversation_id": conversation_id,
        "proposed": report.proposed,
        "written": report.written,
        "duplicates": report.duplicates,
        "skipped": report.skipped,
    }
