from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_profile import UserProfile
from app.repositories.profile_repository import ProfileRepository
from app.core.exceptions import ProfileNotFoundError, UsernameTakenError


class ProfileService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ProfileRepository(db)

    async def update_profile(self, user_id, data) -> UserProfile:
        profile = await self.repo.get_by_user_id(user_id)

        if profile is None:
            raise ProfileNotFoundError(user_id)

        changes = data.model_dump(exclude_unset=True)

        new_username = changes.get("username")

        if new_username is not None and new_username != profile.username:
            existing = await self.repo.get_by_username(new_username)
            
            if existing is not None:
                raise UsernameTakenError(new_username)

        try:
            await self.repo.update(profile, changes)
            await self.db.commit()
        except UsernameTakenError:
            await self.db.rollback()
            raise

        await self.db.refresh(profile)
        return profile