from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import OutboxEvent
from app.models.user import User
from app.models.user_profile import UserProfile


class UserRepository:
    """Asynchronous data access repository for User, UserProfile, and OutboxEvent using SQLAlchemy 2.0."""

    async def get_user_by_id(self, session: AsyncSession, user_id: str) -> User | None:
        """Retrieves a user by opaque identifier along with eager profile relation."""
        return await session.get(User, user_id)

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


    async def get_users_by_ids(self, session: AsyncSession, user_ids: list[str]) -> list[User]:
        """Retrieves multiple users by their IDs."""
        stmt = select(User).where(User.id.in_(user_ids))
        result = await session.execute(stmt)
        return list(result.scalars().all())
