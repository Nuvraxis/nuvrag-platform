from datetime import date
from uuid import UUID

from sqlalchemy import CheckConstraint
from sqlmodel import Field, SQLModel

from app.models.base import OrgScopedMixin, TimestampMixin


class ChatbotUsagePeriod(OrgScopedMixin, TimestampMixin, SQLModel, table=True):
    """One chatbot's provider spend for one UTC calendar month.

    Keyed on `(chatbot_id, period_start)` rather than one current row per chatbot. Rolling into
    a new month is then an insert rather than an update that has to decide whether it is
    continuing a period or starting one — and the rows a chatbot leaves behind are already the
    history that a later iteration would otherwise have to reconstruct.

    Carries `org_id` even though `chatbot_id` implies it. Every RLS policy in this schema reads
    `org_id` from the row itself, so a table without one could not be protected the same way as
    its neighbours, and a policy that had to join to `chatbot` to find the tenant would be a
    second pattern to get right.
    """

    __tablename__ = "chatbot_usage_period"
    __table_args__ = (
        # A counter only ever goes up. A negative one would mean the increment statement
        # had been asked to subtract, which is worth failing loudly rather than storing.
        CheckConstraint("ingestion_units_used >= 0", name="ingestion_units_used"),
        CheckConstraint("retrieval_calls_used >= 0", name="retrieval_calls_used"),
    )

    chatbot_id: UUID = Field(
        foreign_key="chatbot.id", ondelete="CASCADE", primary_key=True, nullable=False
    )
    # The first day of the month, in UTC. A date rather than a timestamp because the boundary
    # is a calendar one: what matters is which month a call belongs to, not the instant.
    period_start: date = Field(primary_key=True, nullable=False)

    ingestion_units_used: int = Field(
        default=0, nullable=False, sa_column_kwargs={"server_default": "0"}
    )
    retrieval_calls_used: int = Field(
        default=0, nullable=False, sa_column_kwargs={"server_default": "0"}
    )
