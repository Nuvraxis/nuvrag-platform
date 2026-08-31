"""Hybrid search: a lexical index beside the vector one

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-31

Vector search cannot match what an embedding does not distinguish. A part number, an
acronym or a rare proper noun lands in much the same place in embedding space as its
neighbours, which is exactly what lexical search is good at and dense retrieval is not. This
adds the lexical half.

`content_tsv` is a **generated** column rather than one the ingestion pipeline maintains, so
it cannot drift from the text it describes and a re-processed document cannot be left holding
the search terms of the passage it replaced. Its configuration is a literal because a
generated column's expression must be immutable — see `TEXT_SEARCH_CONFIG` in the model for
what one language for the whole deployment costs.

The GIN index covers `(chatbot_id, content_tsv)` rather than the tsvector alone, which is
what `btree_gin` is enabled for. Measured on 60,000 chunks across twelve chatbots, a plain GIN
over the tsvector was not used at all: a natural-language question ORed into its lexemes
matches most of a corpus, so the planner preferred the chatbot btree and filtered in the heap.
The composite answers both halves at once.

It is declared on the **parent**, like every btree index in 0008, so Postgres creates and
maintains it on every partition including ones added later. The HNSW index next to it needs
per-partition DDL only because `embedding::vector(N)` differs per partition; this one does
not.

Adding a stored generated column rewrites the table. On an empty or small `document_chunk`
that is nothing; on a large one it is a rewrite plus a GIN build, and it takes an ACCESS
EXCLUSIVE lock for the duration.

`secret_key_hash` gains a unique index. The column has existed since 0002 and has only ever
been written; `POST /api/v1/search` is the first thing to look a chatbot *up* by it, and an
auth path cannot be a sequential scan of every chatbot on the platform.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors `TEXT_SEARCH_CONFIG` in app/models/document_chunk.py.
TEXT_SEARCH_CONFIG = "english"

TSV_COLUMN = "content_tsv"
TSV_INDEX = "ix_document_chunk_chatbot_id_content_tsv"
SECRET_INDEX = "ix_chatbot_secret_key_hash"

TOGGLES = ("hybrid_search_enabled", "hybrid_rerank_enabled")


def upgrade() -> None:
    op.add_column(
        "document_chunk",
        sa.Column(
            TSV_COLUMN,
            postgresql.TSVECTOR(),
            sa.Computed(f"to_tsvector('{TEXT_SEARCH_CONFIG}', content)", persisted=True),
            nullable=True,
        ),
    )
    # `btree_gin` is what lets a uuid share a GIN index with a tsvector. Without it the two
    # halves of the predicate need two indexes, and the planner measurably prefers to use
    # neither — see the note on the index in app/models/document_chunk.py.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")
    op.create_index(
        TSV_INDEX,
        "document_chunk",
        ["chatbot_id", TSV_COLUMN],
        postgresql_using="gin",
    )

    for column in TOGGLES:
        op.add_column(
            "chatbot",
            sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )

    op.create_index(SECRET_INDEX, "chatbot", ["secret_key_hash"], unique=True)


def downgrade() -> None:
    op.drop_index(SECRET_INDEX, table_name="chatbot")
    for column in reversed(TOGGLES):
        op.drop_column("chatbot", column)
    op.drop_index(TSV_INDEX, table_name="document_chunk")
    op.drop_column("document_chunk", TSV_COLUMN)
