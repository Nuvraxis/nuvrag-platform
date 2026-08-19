from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.config import settings
from app.models import Plan, UserRole


class SignupRequest(BaseModel):
    """Creates the organisation and its first owner in one step."""

    organization_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    # The bound is a setting, so it is applied here rather than as a static `min_length` —
    # otherwise the published OpenAPI schema would advertise a different minimum from the one
    # actually enforced.
    password: str = Field(
        max_length=256,
        description=f"At least {settings.security.password_min_length} characters",
    )
    full_name: str | None = Field(default=None, max_length=200)

    @field_validator("password")
    @classmethod
    def enforce_minimum_length(cls, value: str) -> str:
        minimum = settings.security.password_min_length
        if len(value) < minimum:
            raise ValueError(f"Password must be at least {minimum} characters")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    email: str
    full_name: str | None
    role: UserRole
    is_active: bool
    created_at: datetime


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    plan: Plan
    created_at: datetime


class SignupResponse(BaseModel):
    organization: OrganizationRead
    user: UserRead
    tokens: TokenPair
