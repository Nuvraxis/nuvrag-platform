from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.config import settings
from app.models import InvitationStatus, UserRole
from app.schemas.auth import OrganizationRead, TokenPair, UserRead


class InvitationCreate(BaseModel):
    email: EmailStr
    role: UserRole = UserRole.MEMBER


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    email: str
    role: UserRole
    status: InvitationStatus
    expires_at: datetime
    invited_by: UUID | None
    accepted_at: datetime | None
    created_at: datetime


class InvitationCreated(BaseModel):
    """The token is returned exactly once.

    There is no mail transport in this deployment, so the caller is responsible for getting
    `accept_url` to the invitee. Once this response is discarded the only way back is to
    revoke the invitation and issue another.
    """

    invitation: InvitationRead
    token: str
    accept_url: str


class MemberUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=16, max_length=256)
    # Mirrors SignupRequest: the bound is a setting, so it is enforced in a validator rather
    # than advertised as a static `min_length` the API might not actually apply.
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


class AcceptInvitationResponse(BaseModel):
    organization: OrganizationRead
    user: UserRead
    tokens: TokenPair


class InvitationPreview(BaseModel):
    """What the sign-up page may show before the invitee has proved anything.

    The organisation name and the role are enough to make the page meaningful; the inviter's
    identity and the rest of the team are not disclosed to someone holding only a link.
    """

    organization_name: str
    email: str
    role: UserRole
    expires_at: datetime


class TeamMembers(BaseModel):
    members: list[UserRead]
