from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import text

from app.core.config import DatabaseSettings, settings

TENANT_GUC = "app.current_org_id"

_engines: dict[str, AsyncEngine] = {}
_session_factories: dict[str, async_sessionmaker[AsyncSession]] = {}


def _connect_args(config: DatabaseSettings) -> dict[str, Any]:
    args: dict[str, Any] = {
        "server_settings": {
            "application_name": settings.observability.service_name,
            "statement_timeout": str(config.statement_timeout_ms),
        }
    }
    if config.pgbouncer_transaction_mode:
        # PgBouncer in transaction mode multiplexes server connections, so asyncpg must not
        # rely on server-side prepared statements surviving between transactions.
        args["statement_cache_size"] = 0
    return args


def _build_engine(dsn: str, config: DatabaseSettings) -> AsyncEngine:
    kwargs: dict[str, Any] = {
        "echo": config.echo,
        "pool_pre_ping": config.pool_pre_ping,
        "connect_args": _connect_args(config),
        "future": True,
    }
    if config.pgbouncer_transaction_mode:
        kwargs["poolclass"] = NullPool
    else:
        kwargs |= {
            "pool_size": config.pool_size,
            "max_overflow": config.max_overflow,
            "pool_recycle": config.pool_recycle_seconds,
        }
    return create_async_engine(dsn, **kwargs)


def _get_engine(kind: str) -> AsyncEngine:
    if kind not in _engines:
        config = settings.database
        # `str()` wraps the whole expression, not just the fallback. These fields are
        # `PostgresDsn`, which in Pydantic v2 is a `Url` object rather than a string, and
        # SQLAlchemy rejects it with `Expected string or URL object`. Wrapping only the
        # fallback hid that everywhere `DB_PRIVILEGED_DSN` is unset — which is every
        # development machine, and no production one.
        dsn = {
            "primary": str(config.dsn),
            "replica": str(config.read_replica_dsn or config.dsn),
            "privileged": str(config.privileged_dsn or config.dsn),
        }[kind]
        _engines[kind] = _build_engine(dsn, config)
    return _engines[kind]


def _get_session_factory(kind: str) -> async_sessionmaker[AsyncSession]:
    if kind not in _session_factories:
        _session_factories[kind] = async_sessionmaker(
            bind=_get_engine(kind),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factories[kind]


def get_engine() -> AsyncEngine:
    return _get_engine("primary")


async def dispose_engines() -> None:
    for engine in _engines.values():
        await engine.dispose()
    _engines.clear()
    _session_factories.clear()


async def _apply_tenant_guc(session: AsyncSession, org_id: UUID) -> None:
    """Scope the transaction to one tenant so RLS policies can enforce isolation.

    SET LOCAL cannot take a bind parameter, so the value is interpolated — safe only because
    `org_id` is a UUID instance, never caller-supplied text.
    """
    await session.execute(text(f"SET LOCAL {TENANT_GUC} = '{UUID(str(org_id))}'"))


@asynccontextmanager
async def tenant_session(org_id: UUID, *, readonly: bool = False) -> AsyncGenerator[AsyncSession]:
    """Primary entry point for tenant data access. Every statement runs under RLS."""
    factory = _get_session_factory("replica" if readonly else "primary")
    async with factory() as session:
        await session.begin()
        try:
            await _apply_tenant_guc(session, org_id)
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


@asynccontextmanager
async def system_session() -> AsyncGenerator[AsyncSession]:
    """Unscoped session for the few operations that legitimately precede tenant context:
    login lookups by email, organisation signup, and health checks.

    It connects with the privileged role (table owner) when one is configured, which is how
    RLS is bypassed in production; in local dev the app already owns the tables.
    """
    factory = _get_session_factory("privileged")
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def check_database_health() -> bool:
    try:
        async with _get_engine("primary").connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - health probes must never raise
        return False
