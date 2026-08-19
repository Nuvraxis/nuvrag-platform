import sys

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging, worker_process_shutdown, worker_shutdown

from app.core.config import settings
from app.core.logging import configure_logging

INGESTION_QUEUE = "ingestion"
DEFAULT_QUEUE = "default"

# Production runs on Linux, where prefork gives real process isolation and parallel PDF
# parsing. Windows has no fork() and no POSIX semaphores, so billiard's prefork children die
# with WinError 5 before they ever accept a task. Threads are the workable substitute for
# local development: ingestion is dominated by network I/O (blob fetch, Azure embeddings,
# Postgres) which releases the GIL anyway. An explicit --pool on the command line still wins.
_IS_WINDOWS = sys.platform == "win32"

celery_app = Celery(
    "rag",
    broker=settings.redis.broker,
    backend=settings.redis.result_backend,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_default_queue=DEFAULT_QUEUE,
    task_routes={
        # File processing is slow and bursty; keeping it on its own queue means a tenant
        # bulk-uploading 50 PDFs cannot starve lightweight background work.
        "ingestion.*": {"queue": INGESTION_QUEUE},
        "maintenance.*": {"queue": DEFAULT_QUEUE},
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    task_time_limit=1800,
    # SIGUSR1 does not exist on Windows, so a soft limit there is silently unenforceable
    # and only produces a startup warning.
    task_soft_time_limit=None if _IS_WINDOWS else 1680,
    worker_pool="threads" if _IS_WINDOWS else "prefork",
    worker_prefetch_multiplier=1,
    # Recycling a worker after N tasks bounds any leak in a parser; it only applies to
    # process-based pools.
    worker_max_tasks_per_child=None if _IS_WINDOWS else 200,
    broker_connection_retry_on_startup=True,
    result_expires=86400,
    timezone="UTC",
    enable_utc=True,
)


RETENTION_TASK = "maintenance.purge_expired_conversations"

# Read by `celery beat`, which is a **separate process from the worker** and must be a
# singleton — two schedulers means every task fires twice. The chart runs it as its own
# one-replica Deployment; see `infra/helm/rag-platform/templates/beat.yaml`.
#
# A worker started without beat simply never receives these, which is why the sweep is the
# only thing on the schedule: nothing the platform needs to stay correct depends on it
# running, so an operator who does not deploy beat loses retention and nothing else.
if settings.retention.enabled:
    celery_app.conf.beat_schedule = {
        "purge-expired-conversations": {
            "task": RETENTION_TASK,
            "schedule": crontab(
                hour=settings.retention.purge_hour_utc,
                minute=settings.retention.purge_minute_utc,
            ),
            # `expires` matters more than the schedule does. Without it a week of firings
            # with no worker up queues seven sweeps that all run the moment one starts;
            # with it the stale ones are discarded and the next scheduled run does the work.
            "options": {"queue": DEFAULT_QUEUE, "expires": 60 * 60 * 6},
        }
    }


@setup_logging.connect
def _configure_worker_logging(**_kwargs) -> None:
    """Celery replaces logging config by default; route it through structlog instead so API
    and worker emit the same JSON shape."""
    configure_logging(settings.observability)


# `worker_process_shutdown` only fires for prefork children, so the thread and solo pools
# need `worker_shutdown` on the main process to release their connections too.
@worker_process_shutdown.connect
@worker_shutdown.connect
def _dispose_resources(**_kwargs) -> None:
    from app.worker.runtime import shutdown

    shutdown()
