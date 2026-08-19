from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from app.models.base import (
    OrgScopedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    enum_column,
)
from app.models.enums import UserRole


class User(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, SQLModel, table=True):
    # "user" is reserved in Postgres; an explicit name keeps raw SQL (RLS policies) unquoted.
    __tablename__ = "app_user"
    __table_args__ = (
        Index("ix_app_user_org_id_email", "org_id", "email"),
        enum_check("role", UserRole),
    )

    email: str = Field(max_length=320, unique=True, index=True, nullable=False)
    hashed_password: str = Field(max_length=255, nullable=False)
    full_name: str | None = Field(default=None, max_length=200)
    role: UserRole = Field(
        default=UserRole.MEMBER, sa_type=enum_column(UserRole, name="role"), nullable=False
    )
    is_active: bool = Field(default=True, nullable=False)
