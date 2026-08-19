"""HNSW vector index and row-level security policies

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-10

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Kept in sync with app.models.base.TENANT_SCOPED_TABLES.
TENANT_TABLES = (
    "app_user",
    "chatbot",
    "document",
    "document_chunk",
    "conversation",
    "message",
)

TENANT_GUC = "app.current_org_id"
POLICY_NAME = "tenant_isolation"

# HNSW beats IVFFlat on recall/latency for a read-heavy chat workload. Build time is the
# tradeoff, which is acceptable because ingestion is already asynchronous.
HNSW_M = 16
HNSW_EF_CONSTRUCTION = 64


def upgrade() -> None:
    op.execute(
        f"""
        CREATE INDEX ix_document_chunk_embedding_hnsw
        ON document_chunk
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = {HNSW_M}, ef_construction = {HNSW_EF_CONSTRUCTION})
        """
    )

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # An unset GUC yields NULL, so the predicate is never true and the table reads as
        # empty. Isolation therefore fails closed rather than open.
        op.execute(
            f"""
            CREATE POLICY {POLICY_NAME} ON {table}
            USING (org_id = NULLIF(current_setting('{TENANT_GUC}', true), '')::uuid)
            WITH CHECK (org_id = NULLIF(current_setting('{TENANT_GUC}', true), '')::uuid)
            """
        )


def downgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY_NAME} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS ix_document_chunk_embedding_hnsw")
