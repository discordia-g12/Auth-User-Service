import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AvatarUploadError, UsernameTakenError, UserProfileNotFoundError
from app.models.user_profile import UserProfile
from app.repositories.profile_repository import ProfileRepository
from app.services.cloudinary_service import upload_avatar as cloudinary_upload_avatar


class ProfileService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ProfileRepository(db)

    async def update_profile(self, user_id, data) -> UserProfile:
        profile = await self.repo.get_by_user_id(user_id)

        if profile is None:
            raise UserProfileNotFoundError()

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

    async def upload_avatar(self, user_id, contents) -> UserProfile:
        profile = await self.repo.get_by_user_id(user_id)

        if profile is None:
            raise UserProfileNotFoundError()

        # Es bloqueante, lo hacemos async (espera a que el thread termine, pero sin bloquear el event loop)
        avatar_url = await asyncio.to_thread(cloudinary_upload_avatar, contents, user_id)

        try:
            await self.repo.update_avatar(profile, avatar_url)
            await self.repo.add_outbox_event(
                event_type="user.profile.updated",
                aggregate_id=user_id,
                payload={
                    "user_id": user_id,
                    "avatar_url": avatar_url,
                },
            )
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise AvatarUploadError("Could not upload new avatar") from None

        await self.db.refresh(profile)
        return profile
