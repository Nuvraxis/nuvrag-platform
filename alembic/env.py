import asyncio
from logging.config import fileConfig

import app.models  # noqa: F401 - import for the side effect of registering every table
from alembic import context
from app.core.config import settings
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Migrations must run as the table owner, which is a different role from the one the API
# uses at runtime once RLS is in force.
config.set_main_option(
    "sqlalchemy.url",
    (settings.database.privileged_dsn and str(settings.database.privileged_dsn))
    or str(settings.database.dsn),
)

target_metadata = SQLModel.metadata


# Partitions of `document_chunk` (migration 0008) and `memory_entry` (0012). They are
# ordinary tables to reflection, so without this each reads as several tables and a pile of
# indexes nobody declared. Every partitioned table has to be listed here — a new one whose
# prefix is missing makes `alembic check` demand its partitions be dropped.
_PARTITION_PREFIXES = ("document_chunk_p", "memory_entry_p")


def _include_object(obj, name: str, type_: str, reflected: bool, compare_to) -> bool:
    """Hide from autogenerate the objects it has no way to describe.

    Two kinds. pgvector's HNSW indexes are raw DDL — an opclass, build parameters, and since
    0008 a cast expression, none of which SQLAlchemy can render. And a partition is a
    property of its parent table rather than a model of its own, so proposing to drop one
    would be proposing to drop the data.
    """
    if type_ == "index" and name and name.endswith("_embedding_hnsw"):
        return False
    return not (reflected and name and name.startswith(_PARTITION_PREFIXES))


def _configure(connection: Connection | None = None, **kwargs) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
        render_as_batch=False,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(
        url=config.get_main_option("sqlalchemy.url"),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_sync_migrations(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run_sync_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
