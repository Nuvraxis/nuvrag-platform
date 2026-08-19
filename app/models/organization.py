from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin, enum_check, enum_column
from app.models.enums import Plan


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "organization"
    __table_args__ = (enum_check("plan", Plan),)

    name: str = Field(max_length=200, nullable=False)
    slug: str = Field(max_length=100, unique=True, index=True, nullable=False)
    plan: Plan = Field(default=Plan.FREE, sa_type=enum_column(Plan, name="plan"), nullable=False)
