"""nuvrag_mem: a per-chatbot similarity floor instead of one global constant

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-30

Three nullable columns on `chatbot`, replacing `NUVRAG_MEM_RETRIEVAL_MIN_SIMILARITY` — one
number for a whole deployment, applied to chatbots that each choose their own embedding
provider and model. Cosine similarity distributions belong to a model, so no single number
was ever right for all of them: measured on nomic-embed-text a paraphrase scores 0.542 and
unrelated questions 0.373-0.431, while on qwen3-embedding:8b the same note scores 0.720 and
0.476-0.526 — the shipped 0.45 separates the first pair of bands and sits below both of the
second.

`nuvrag_mem_similarity_override` is what an operator decided; `nuvrag_mem_similarity_calibrated`
is what the chatbot's own embedding model measured. NULL on the calibrated column is what
makes the next recall attempt measure it, so — as ever since 0013 — neither column carries a
default of any kind, server-side or otherwise. Existing rows therefore arrive uncalibrated,
which is correct rather than a gap: nothing is backfilled because there is nothing to backfill
from, and the first returning visitor on each chatbot triggers the measurement.

No RLS work. These are columns on `chatbot`, which has had its policy since 0003, and a
policy covers whatever columns the table has.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)

# Mirrors `SIMILARITY_MIN` / `SIMILARITY_MAX` in app/models/chatbot.py.
SIMILARITY_MIN = 0.0
SIMILARITY_MAX = 1.0

THRESHOLD_COLUMNS = ("nuvrag_mem_similarity_override", "nuvrag_mem_similarity_calibrated")
TIMESTAMP_COLUMN = "nuvrag_mem_similarity_calibrated_at"


def _threshold_check(column: str) -> str:
    return f"{column} IS NULL OR {column} BETWEEN {SIMILARITY_MIN} AND {SIMILARITY_MAX}"


def upgrade() -> None:
    for column in THRESHOLD_COLUMNS:
        op.add_column("chatbot", sa.Column(column, sa.Float(), nullable=True))
        # Raw rather than `op.create_check_constraint`, matching 0009, 0012 and 0014: the
        # helper feeds the name back through the metadata naming convention and expands an
        # already-expanded name a second time.
        op.execute(
            f"ALTER TABLE chatbot ADD CONSTRAINT ck_chatbot_{column} "
            f"CHECK ({_threshold_check(column)})"
        )

    op.add_column("chatbot", sa.Column(TIMESTAMP_COLUMN, _TS, nullable=True))


def downgrade() -> None:
    op.drop_column("chatbot", TIMESTAMP_COLUMN)
    for column in THRESHOLD_COLUMNS:
        op.execute(f"ALTER TABLE chatbot DROP CONSTRAINT IF EXISTS ck_chatbot_{column}")
        op.drop_column("chatbot", column)
