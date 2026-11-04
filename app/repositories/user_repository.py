from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import OutboxEvent
from app.models.user import User
from app.models.user_profile import UserProfile


class UserRepository:
    """Asynchronous data access repository for User, UserProfile, and OutboxEvent using SQLAlchemy 2.0."""

    async def get_user_by_id(self, session: AsyncSession, user_id: str) -> User | None:
        """Retrieves a user by opaque identifier along with eager profile relation."""
        return await session.get(User, user_id)

    async def get_user_by_email(self, session: AsyncSession, email: str) -> User | None:
        """Retrieves a user by email address along with eager profile relation."""
        stmt = select(User).where(User.email == email)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_profile_by_username(self, session: AsyncSession, username: str) -> UserProfile | None:
        """Retrieves a user profile by username to check uniqueness."""
        stmt = select(UserProfile).where(UserProfile.username == username)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_user_profile_and_outbox(
        self,
        session: AsyncSession,
        user_id: str,
        username: str,
        email: str,
        display_name: str | None = None,
        bio: str | None = None,
        avatar_url: str | None = None,
        outbox_payload: dict[str, Any] | None = None,
    ) -> tuple[User, UserProfile]:
        """Atomically inserts User, UserProfile, and OutboxEvent within active transaction."""
        user = User(
            id=user_id,
            email=email,
            is_active=True,
            is_suspended=False,
        )
        session.add(user)

        profile = UserProfile(
            user_id=user_id,
            username=username,
            display_name=display_name,
            bio=bio,
            avatar_url=avatar_url,
            activity_status="offline",
        )
        session.add(profile)

        event_payload = outbox_payload or {
            "user_id": user_id,
            "username": username,
            "email": email,
        }
        outbox_event = OutboxEvent(
            aggregate_type="user",
            aggregate_id=user_id,
            event_type="user.registered",
            payload=event_payload,
        )
        session.add(outbox_event)

        return user, profile


    async def find_user_by_identifier(self, session: AsyncSession, identifier: str) -> User | None:
        """Staff lookup: "@username", an email (case-insensitive), a user id or a bare username."""
        value = identifier.strip()
        if not value:
            return None
        if value.startswith("@"):
            return await self._get_user_by_username(session, value[1:])
        if "@" in value:
            stmt = select(User).where(func.lower(User.email) == value.lower())
            return (await session.execute(stmt)).scalar_one_or_none()
        user = await self.get_user_by_id(session, value)
        if user is not None:
            return user
        return await self._get_user_by_username(session, value)

    async def _get_user_by_username(self, session: AsyncSession, username: str) -> User | None:
        stmt = select(User).join(UserProfile, UserProfile.user_id == User.id).where(UserProfile.username == username)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_alias_ids(self, session: AsyncSession, primary_user_id: str) -> list[str]:
        """Federated identities linked to a user (see ensure_identity_alias)."""
        stmt = select(OutboxEvent).where(OutboxEvent.aggregate_type == "user_identity_alias")
        events = (await session.execute(stmt)).scalars().all()
        return [
            ev.aggregate_id
            for ev in events
            if isinstance(ev.payload, dict) and ev.payload.get("primary_user_id") == primary_user_id
        ]

    async def list_suspended_users(self, session: AsyncSession) -> list[User]:
        """Suspended accounts, most recent first."""
        stmt = select(User).where(User.is_suspended.is_(True)).order_by(User.suspended_at.desc())
        return list((await session.execute(stmt)).scalars().all())

    def add_outbox_event(
        self, session: AsyncSession, user_id: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        """Queues a domain event in the same transaction as the change (ADR-005)."""
        session.add(OutboxEvent(aggregate_type="user", aggregate_id=user_id, event_type=event_type, payload=payload))

    async def get_users_by_ids(self, session: AsyncSession, user_ids: list[str]) -> list[User]:
        """Retrieves multiple users by their IDs."""
        stmt = select(User).where(User.id.in_(user_ids))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def ensure_identity_alias(
        self, session: AsyncSession, alias_id: str, primary_user_id: str
    ) -> None:
        """Persists a federated identity alias mapping to the primary user ID if not already stored."""
        if not alias_id or alias_id == primary_user_id:
            return
        stmt = select(OutboxEvent).where(
            OutboxEvent.aggregate_type == "user_identity_alias",
            OutboxEvent.aggregate_id == alias_id,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is None:
            session.add(
                OutboxEvent(
                    aggregate_type="user_identity_alias",
                    aggregate_id=alias_id,
                    event_type="user.identity_linked",
                    payload={"primary_user_id": primary_user_id},
                    processed_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def get_aliased_users_by_ids(
        self, session: AsyncSession, alias_ids: list[str]
    ) -> dict[str, User]:
        """Resolves federated alias IDs to their linked primary User records."""
        if not alias_ids:
            return {}
        stmt = select(OutboxEvent).where(
            OutboxEvent.aggregate_type == "user_identity_alias",
            OutboxEvent.aggregate_id.in_(alias_ids),
        )
        events = list((await session.execute(stmt)).scalars().all())
        if not events:
            return {}
        alias_to_primary: dict[str, str] = {}
        for ev in events:
            if isinstance(ev.payload, dict):
                prim_id = ev.payload.get("primary_user_id")
                if isinstance(prim_id, str) and prim_id:
                    alias_to_primary[ev.aggregate_id] = prim_id
        if not alias_to_primary:
            return {}
        primary_users = await self.get_users_by_ids(session, list(set(alias_to_primary.values())))
        primary_by_id = {u.id: u for u in primary_users}
        return {
            alias_id: primary_by_id[prim_id]
            for alias_id, prim_id in alias_to_primary.items()
            if prim_id in primary_by_id
        }
