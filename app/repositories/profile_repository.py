from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import UsernameTakenError
from app.models.outbox import OutboxEvent
from app.models.user_profile import UserProfile


class ProfileRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_user_id(self, user_id) -> UserProfile | None:
        result = await self.db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_by_username(self, username) -> UserProfile | None:
        result = await self.db.execute(select(UserProfile).where(UserProfile.username == username))
        return result.scalar_one_or_none()

    async def update(self, profile, changes) -> UserProfile:
        for field, value in changes.items():
            setattr(profile, field, value)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            raise UsernameTakenError(changes.get("username")) from exc
        return profile

    async def update_avatar(self, profile: UserProfile, avatar_url) -> UserProfile:
        profile.avatar_url = avatar_url
        await self.db.flush()
        return profile

    async def add_outbox_event(self, event_type, aggregate_id, payload) -> OutboxEvent:
        event = OutboxEvent(
            aggregate_type="user_profile",
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload=payload,
        )
        self.db.add(event)
        await self.db.flush()
        return event
