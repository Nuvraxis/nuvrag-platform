from uuid import UUID

from sqlmodel import func, select

from app.models import Invitation, InvitationStatus, Organization, User, UserRole
from app.repositories.base import BaseRepository


class OrganizationRepository(BaseRepository[Organization]):
    model = Organization

    async def get_by_slug(self, slug: str) -> Organization | None:
        result = await self.session.execute(select(Organization).where(Organization.slug == slug))
        return result.scalar_one_or_none()


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email.strip().lower()))
        return result.scalar_one_or_none()

    async def list_for_org(self, org_id: UUID) -> list[User]:
        result = await self.session.execute(
            select(User).where(User.org_id == org_id).order_by(User.created_at)
        )
        return list(result.scalars())

    async def count_active_owners(self, org_id: UUID) -> int:
        """Guards the "an organisation always keeps an owner" rule.

        Deactivated owners do not count: an account nobody can sign in to cannot restore
        anyone else's access.
        """
        result = await self.session.execute(
            select(func.count())
            .select_from(User)
            .where(
                User.org_id == org_id,
                User.role == UserRole.OWNER,
                User.is_active.is_(True),
            )
        )
        return int(result.scalar_one())


class InvitationRepository(BaseRepository[Invitation]):
    model = Invitation

    async def get_by_token_hash(self, token_hash: str) -> Invitation | None:
        result = await self.session.execute(
            select(Invitation).where(Invitation.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def get_pending(self, org_id: UUID, email: str) -> Invitation | None:
        result = await self.session.execute(
            select(Invitation).where(
                Invitation.org_id == org_id,
                Invitation.email == email.strip().lower(),
                Invitation.status == InvitationStatus.PENDING,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_org(
        self, org_id: UUID, *, status: InvitationStatus | None = None
    ) -> list[Invitation]:
        stmt = select(Invitation).where(Invitation.org_id == org_id)
        if status is not None:
            stmt = stmt.where(Invitation.status == status)
        result = await self.session.execute(stmt.order_by(Invitation.created_at.desc()))
        return list(result.scalars())
