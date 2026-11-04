from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.suspension import PlatformUserSummary

logger = get_logger(__name__)


class IdentityBlocker(Protocol):
    async def set_blocked(self, user_id: str, blocked: bool) -> None: ...


class Denylist(Protocol):
    async def add(self, user_ids: list[str], email: str) -> None: ...

    async def remove(self, user_ids: list[str], email: str) -> None: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


def to_summary(user: User) -> PlatformUserSummary:
    profile = user.profile
    return PlatformUserSummary(
        user_id=user.id,
        username=profile.username if profile else None,
        display_name=profile.display_name if profile else None,
        email=user.email,
        is_suspended=user.is_suspended,
        suspended_at=user.suspended_at,
        suspended_by=user.suspended_by,
        suspension_reason=user.suspension_reason,
        created_at=user.created_at,
    )


class SuspensionService:
    """Platform-level suspension (ADR-002): Auth0 block → Gateway denylist → DB + user.suspended event.

    Each step is idempotent, so a failed operation is retried as a whole: if Auth0 or Redis fail nothing is
    committed (503), and blocking an already blocked identity again is harmless. The DB change and the
    event go in the same transaction (Outbox, ADR-005); Chat and Voice react to the event by closing the
    user's live connections.
    """

    def __init__(
        self,
        blocker: IdentityBlocker,
        denylist: Denylist,
        user_repo: UserRepository | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ):
        self.blocker = blocker
        self.denylist = denylist
        self.user_repo = user_repo or UserRepository()
        self.clock = clock

    async def _identities(self, session: AsyncSession, user: User) -> list[str]:
        return [user.id, *await self.user_repo.get_alias_ids(session, user.id)]

    async def suspend(
        self, session: AsyncSession, identifier: str, reason: str, staff_user_id: str
    ) -> PlatformUserSummary:
        user = await self.user_repo.find_user_by_identifier(session, identifier)
        if user is None:
            raise NotFoundError("No account matches that email, @username or id.")
        identities = await self._identities(session, user)
        if staff_user_id in identities:
            raise BadRequestError("Staff cannot suspend their own account.")
        if user.is_suspended:
            raise ConflictError("The account is already suspended.")

        for identity in identities:
            await self.blocker.set_blocked(identity, True)
        await self.denylist.add(identities, user.email)

        now = self.clock()
        user.is_suspended = True
        user.suspended_at = now
        user.suspended_by = staff_user_id
        user.suspension_reason = reason.strip()
        self.user_repo.add_outbox_event(
            session,
            user.id,
            "user.suspended",
            {
                "user_id": user.id,
                "identities": identities,
                "reason": user.suspension_reason,
                "suspended_by": staff_user_id,
                "suspended_at": now.isoformat(),
            },
        )
        # La respuesta se arma antes del commit: después, los atributos pueden quedar expirados
        summary = to_summary(user)
        await session.commit()
        logger.info("user_suspended", user_id=user.id, suspended_by=staff_user_id, identities=len(identities))
        return summary

    async def reactivate(self, session: AsyncSession, user_id: str, staff_user_id: str) -> PlatformUserSummary:
        user = await self.user_repo.get_user_by_id(session, user_id)
        if user is None:
            raise NotFoundError("Account not found.")
        if not user.is_suspended:
            raise ConflictError("The account is not suspended.")
        identities = await self._identities(session, user)

        for identity in identities:
            await self.blocker.set_blocked(identity, False)
        await self.denylist.remove(identities, user.email)

        user.is_suspended = False
        user.suspended_at = None
        user.suspended_by = None
        user.suspension_reason = None
        self.user_repo.add_outbox_event(
            session,
            user.id,
            "user.reactivated",
            {
                "user_id": user.id,
                "identities": identities,
                "reactivated_by": staff_user_id,
                "reactivated_at": self.clock().isoformat(),
            },
        )
        summary = to_summary(user)
        await session.commit()
        logger.info("user_reactivated", user_id=user.id, reactivated_by=staff_user_id)
        return summary

    async def list_suspended(self, session: AsyncSession) -> list[PlatformUserSummary]:
        return [to_summary(user) for user in await self.user_repo.list_suspended_users(session)]
