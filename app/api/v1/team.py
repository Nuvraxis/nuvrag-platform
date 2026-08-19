from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentPrincipal, RequireAdmin
from app.models import InvitationStatus
from app.schemas.auth import UserRead
from app.schemas.team import (
    InvitationCreate,
    InvitationCreated,
    InvitationRead,
    MemberUpdate,
    TeamMembers,
)
from app.services import team as team_service

router = APIRouter(prefix="/team", tags=["team"])


@router.get("/members", response_model=TeamMembers)
async def list_members(principal: CurrentPrincipal) -> TeamMembers:
    """Readable by any member: knowing who else is in your organisation is not privileged."""
    members = await team_service.list_members(principal.org_id)
    return TeamMembers(members=[UserRead.model_validate(member) for member in members])


@router.patch("/members/{user_id}", response_model=UserRead)
async def update_member(user_id: UUID, payload: MemberUpdate, principal: RequireAdmin) -> UserRead:
    member = await team_service.update_member(principal.org_id, principal.user, user_id, payload)
    return UserRead.model_validate(member)


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(user_id: UUID, principal: RequireAdmin) -> None:
    await team_service.remove_member(principal.org_id, principal.user, user_id)


@router.post("/invitations", response_model=InvitationCreated, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    payload: InvitationCreate, principal: RequireAdmin
) -> InvitationCreated:
    """The response carries the only copy of the token; it is not stored in plaintext."""
    invitation, token = await team_service.invite_member(principal.org_id, principal.user, payload)
    return InvitationCreated(
        invitation=InvitationRead.model_validate(invitation),
        token=token,
        accept_url=team_service.build_accept_url(token),
    )


@router.get("/invitations", response_model=list[InvitationRead])
async def list_invitations(
    principal: RequireAdmin,
    status_filter: InvitationStatus | None = Query(default=None, alias="status"),
) -> list[InvitationRead]:
    invitations = await team_service.list_invitations(principal.org_id, status=status_filter)
    return [InvitationRead.model_validate(invitation) for invitation in invitations]


@router.delete("/invitations/{invitation_id}", response_model=InvitationRead)
async def revoke_invitation(invitation_id: UUID, principal: RequireAdmin) -> InvitationRead:
    invitation = await team_service.revoke_invitation(principal.org_id, invitation_id)
    return InvitationRead.model_validate(invitation)
