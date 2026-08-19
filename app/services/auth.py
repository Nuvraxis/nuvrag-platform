from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.exceptions import AuthenticationError, ConflictError, NotFoundError
from app.core.security import create_token, decode_token, hash_password, verify_password
from app.core.slug import slugify, unique_slug
from app.db.session import system_session, tenant_session
from app.models import Organization, User, UserRole
from app.repositories import OrganizationRepository, UserRepository
from app.schemas.auth import TokenPair
from app.services import revocation

SLUG_MAX_LENGTH = 100


def issue_tokens(user: User) -> TokenPair:
    config = settings.security
    return TokenPair(
        access_token=create_token(
            subject=user.id,
            org_id=user.org_id,
            role=str(user.role),
            token_type="access",
            config=config,
        ),
        refresh_token=create_token(
            subject=user.id,
            org_id=user.org_id,
            role=str(user.role),
            token_type="refresh",
            config=config,
        ),
        expires_in=config.access_token_ttl_seconds,
    )


async def signup(
    *, organization_name: str, email: str, password: str, full_name: str | None
) -> tuple[Organization, User, TokenPair]:
    """Bootstraps a tenant. Runs unscoped because no tenant context exists yet."""
    normalised_email = email.strip().lower()

    async with system_session() as session:
        user_repo = UserRepository(session)
        if await user_repo.get_by_email(normalised_email) is not None:
            raise ConflictError("An account with that email already exists")

        org_repo = OrganizationRepository(session)

        async def slug_taken(candidate: str) -> bool:
            return await org_repo.get_by_slug(candidate) is not None

        organization = await org_repo.add(
            Organization(
                name=organization_name.strip(),
                slug=await unique_slug(
                    slugify(organization_name, max_length=SLUG_MAX_LENGTH, fallback="org"),
                    slug_taken,
                    max_length=SLUG_MAX_LENGTH,
                ),
            )
        )
        user = await user_repo.add(
            User(
                org_id=organization.id,
                email=normalised_email,
                hashed_password=hash_password(password),
                full_name=full_name.strip() if full_name else None,
                role=UserRole.OWNER,
            )
        )

    return organization, user, issue_tokens(user)


async def authenticate(*, email: str, password: str) -> tuple[User, TokenPair]:
    async with system_session() as session:
        user = await UserRepository(session).get_by_email(email.strip().lower())

    # The password is verified even when no user matched, so response timing does not
    # reveal which addresses are registered.
    reference_hash = user.hashed_password if user else hash_password("timing-equaliser")
    password_ok = verify_password(password, reference_hash)

    if user is None or not password_ok:
        raise AuthenticationError("Incorrect email or password")
    if not user.is_active:
        raise AuthenticationError("This account has been deactivated")

    return user, issue_tokens(user)


def _expiry_of(payload: dict[str, Any]) -> datetime | None:
    exp = payload.get("exp")
    return datetime.fromtimestamp(exp, tz=UTC) if isinstance(exp, int) else None


async def refresh_tokens(refresh_token: str) -> TokenPair:
    payload = decode_token(refresh_token, expected_type="refresh", config=settings.security)
    user_id = UUID(payload["sub"])

    if await revocation.is_token_revoked(payload.get("jti")):
        raise AuthenticationError("This session has been signed out")
    if await revocation.issued_before_cutoff(user_id, payload.get("iat")):
        raise AuthenticationError("This session is no longer valid")

    user = await get_active_user(UUID(payload["org"]), user_id)
    return issue_tokens(user)


async def logout(refresh_token: str) -> None:
    """Retire one session.

    Deliberately silent about a token it cannot read: signing out is idempotent, and a client
    holding a expired or malformed token has already achieved what it asked for. Returning
    401 here would only make the dashboard's sign-out button fail at the moment it matters
    least.
    """
    try:
        payload = decode_token(refresh_token, expected_type="refresh", config=settings.security)
    except AuthenticationError:
        return

    jti = payload.get("jti")
    if jti:
        await revocation.revoke_token(jti, expires_at=_expiry_of(payload))


async def get_active_user(org_id: UUID, user_id: UUID) -> User:
    async with tenant_session(org_id, readonly=True) as session:
        user = await UserRepository(session).get(user_id)

    if user is None:
        raise NotFoundError("User no longer exists")
    if not user.is_active:
        raise AuthenticationError("This account has been deactivated")
    return user
