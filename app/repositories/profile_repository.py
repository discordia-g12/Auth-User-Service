from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_profile import UserProfile
from app.core.exceptions import UsernameTakenError

class ProfileRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_user_id(self, user_id: str) -> UserProfile | None:
        result = await self.db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> UserProfile | None:
        result = await self.db.execute(select(UserProfile).where(UserProfile.username == username))
        return result.scalar_one_or_none()

    async def update(self, profile, changes: dict) -> UserProfile:
        for field, value in changes.items():
            setattr(profile, field, value)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            raise UsernameTakenError(changes.get("username")) from exc
        return profile
