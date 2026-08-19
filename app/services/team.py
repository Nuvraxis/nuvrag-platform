import secrets
from datetime import timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.logging import get_logger
from app.core.security import hash_api_key, hash_password, utcnow
from app.db.session import system_session, tenant_session
from app.models import Invitation, InvitationStatus, Organization, User, UserRole
from app.repositories import InvitationRepository, OrganizationRepository, UserRepository
from app.schemas.auth import TokenPair
from app.schemas.team import InvitationCreate, MemberUpdate
from app.services import revocation
from app.services.auth import issue_tokens

logger = get_logger(__name__)

TOKEN_BYTES = 32


def build_accept_url(token: str) -> str:
    return f"{settings.dashboard_base_url.rstrip('/')}/accept-invitation?token={token}"


async def list_members(org_id: UUID) -> list[User]:
    async with tenant_session(org_id, readonly=True) as session:
        return await UserRepository(session).list_for_org(org_id)


async def invite_member(
    org_id: UUID, actor: User, payload: InvitationCreate
) -> tuple[Invitation, str]:
    """Create a pending invitation and return its one-time token."""
    email = str(payload.email).strip().lower()
    role = UserRole(payload.role)

    # Nobody may hand out more authority than they hold, which is what stops an admin from
    # promoting themselves via a self-addressed owner invitation.
    if not UserRole(actor.role).can_act_as(role):
        raise PermissionDeniedError(f"You cannot invite someone as {role}")

    token = secrets.token_urlsafe(TOKEN_BYTES)
    invitation = Invitation(
        org_id=org_id,
        email=email,
        role=role,
        token_hash=hash_api_key(token),
        expires_at=utcnow() + timedelta(seconds=settings.security.invitation_ttl_seconds),
        invited_by=actor.id,
    )

    # Email is unique across the whole platform, so an address already in use anywhere can
    # never accept. Saying so up front beats a dead link discovered a day later.
    async with system_session() as session:
        if await UserRepository(session).get_by_email(email) is not None:
            raise ConflictError("An account with that email already exists")

    try:
        async with tenant_session(org_id) as session:
            stored = await InvitationRepository(session).add(invitation)
    except IntegrityError as exc:
        # The partial unique index is the arbiter; two admins inviting the same person at
        # once means one of them loses, and there is already a live invitation to use.
        raise ConflictError("That address already has a pending invitation") from exc

    logger.info(
        "team.invitation_created", org_id=str(org_id), invitation_id=str(stored.id), role=str(role)
    )
    return stored, token


async def list_invitations(
    org_id: UUID, *, status: InvitationStatus | None = None
) -> list[Invitation]:
    async with tenant_session(org_id, readonly=True) as session:
        return await InvitationRepository(session).list_for_org(org_id, status=status)


async def revoke_invitation(org_id: UUID, invitation_id: UUID) -> Invitation:
    async with tenant_session(org_id) as session:
        repo = InvitationRepository(session)
        invitation = await repo.get(invitation_id)
        if invitation is None or invitation.org_id != org_id:
            raise NotFoundError(f"Invitation {invitation_id} not found")
        if invitation.status != InvitationStatus.PENDING:
            raise ConflictError(f"That invitation is already {invitation.status}")

        invitation.status = InvitationStatus.REVOKED
        session.add(invitation)

    return invitation


async def preview_invitation(token: str) -> tuple[Organization, Invitation]:
    """Resolve a token for the acceptance page. Runs unscoped: the invitee has no session."""
    async with system_session() as session:
        invitation = await InvitationRepository(session).get_by_token_hash(hash_api_key(token))
        _ensure_usable(invitation)
        assert invitation is not None  # narrowed by _ensure_usable

        organization = await OrganizationRepository(session).get(invitation.org_id)
        if organization is None:
            raise NotFoundError("That organisation no longer exists")

    return organization, invitation


async def accept_invitation(
    *, token: str, password: str, full_name: str | None
) -> tuple[Organization, User, TokenPair]:
    async with system_session() as session:
        invitation_repo = InvitationRepository(session)
        invitation = await invitation_repo.get_by_token_hash(hash_api_key(token))
        _ensure_usable(invitation)
        assert invitation is not None

        user_repo = UserRepository(session)
        if await user_repo.get_by_email(invitation.email) is not None:
            raise ConflictError("An account with that email already exists")

        organization = await OrganizationRepository(session).get(invitation.org_id)
        if organization is None:
            raise NotFoundError("That organisation no longer exists")

        user = await user_repo.add(
            User(
                org_id=invitation.org_id,
                email=invitation.email,
                hashed_password=hash_password(password),
                full_name=full_name.strip() if full_name else None,
                role=invitation.role,
            )
        )

        invitation.status = InvitationStatus.ACCEPTED
        invitation.accepted_at = utcnow()
        session.add(invitation)

    logger.info("team.invitation_accepted", org_id=str(organization.id), user_id=str(user.id))
    return organization, user, issue_tokens(user)


async def update_member(org_id: UUID, actor: User, user_id: UUID, payload: MemberUpdate) -> User:
    if payload.role is None and payload.is_active is None:
        raise ValidationError("Nothing to update")

    async with tenant_session(org_id) as session:
        repo = UserRepository(session)
        member = await repo.get(user_id)
        if member is None or member.org_id != org_id:
            raise NotFoundError(f"User {user_id} not found")

        if payload.role is not None:
            await _apply_role_change(repo, actor, member, UserRole(payload.role), org_id)
        if payload.is_active is not None:
            _apply_activation_change(actor, member, payload.is_active)

        session.add(member)

    # A demoted or suspended member must not be able to keep renewing the session they were
    # holding when the change landed.
    await revocation.revoke_all_for_user(member.id)
    logger.info("team.member_updated", org_id=str(org_id), user_id=str(user_id))
    return member


async def remove_member(org_id: UUID, actor: User, user_id: UUID) -> None:
    if actor.id == user_id:
        raise PermissionDeniedError("You cannot remove yourself from the organisation")

    async with tenant_session(org_id) as session:
        repo = UserRepository(session)
        member = await repo.get(user_id)
        if member is None or member.org_id != org_id:
            raise NotFoundError(f"User {user_id} not found")

        if not UserRole(actor.role).can_act_as(UserRole(member.role)):
            raise PermissionDeniedError("You cannot remove someone with a higher role")
        if member.role == UserRole.OWNER and await repo.count_active_owners(org_id) <= 1:
            raise ConflictError("An organisation must always have at least one active owner")

        # Uploads survive: `document.uploaded_by` is ON DELETE SET NULL precisely so removing
        # a colleague never destroys the knowledge base they built.
        await repo.delete(member)

    await revocation.revoke_all_for_user(user_id)
    logger.info("team.member_removed", org_id=str(org_id), user_id=str(user_id))


async def _apply_role_change(
    repo: UserRepository, actor: User, member: User, role: UserRole, org_id: UUID
) -> None:
    actor_role = UserRole(actor.role)
    if not actor_role.can_act_as(role):
        raise PermissionDeniedError(f"You cannot grant the {role} role")
    if not actor_role.can_act_as(UserRole(member.role)):
        raise PermissionDeniedError("You cannot change the role of someone above you")
    if (
        member.role == UserRole.OWNER
        and role != UserRole.OWNER
        and await repo.count_active_owners(org_id) <= 1
    ):
        raise ConflictError("An organisation must always have at least one active owner")

    member.role = role


def _apply_activation_change(actor: User, member: User, is_active: bool) -> None:
    if actor.id == member.id and not is_active:
        raise PermissionDeniedError("You cannot deactivate your own account")
    if not UserRole(actor.role).can_act_as(UserRole(member.role)):
        raise PermissionDeniedError("You cannot suspend someone with a higher role")

    member.is_active = is_active


def _ensure_usable(invitation: Invitation | None) -> None:
    """A wrong, revoked, spent or stale token all produce the same answer.

    Distinguishing them would let someone holding a random string learn whether it once
    named a real invitation.
    """
    if (
        invitation is None
        or invitation.status != InvitationStatus.PENDING
        or invitation.expires_at <= utcnow()
    ):
        raise NotFoundError("That invitation link is not valid")
