from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_two_factor import UserTwoFactor

UNSET = object()


class TwoFactorRepository:
    """Repository for persisting and querying user two-factor authentication records."""

    async def get_by_user_id(self, session: AsyncSession, user_id: str) -> UserTwoFactor | None:
        return await session.get(UserTwoFactor, user_id)

    async def create_or_update(
        self,
        session: AsyncSession,
        user_id: str,
        *,
        is_enabled: Any = UNSET,
        secret: Any = UNSET,
        temp_secret: Any = UNSET,
        recovery_codes: Any = UNSET,
    ) -> UserTwoFactor:
        entity = await self.get_by_user_id(session, user_id)
        if entity is None:
            entity = UserTwoFactor(
                user_id=user_id,
                is_enabled=is_enabled if is_enabled is not UNSET else False,
                secret=secret if secret is not UNSET else None,
                temp_secret=temp_secret if temp_secret is not UNSET else None,
                recovery_codes=recovery_codes if recovery_codes is not UNSET else [],
            )
            session.add(entity)
        else:
            if is_enabled is not UNSET:
                entity.is_enabled = bool(is_enabled)
            if secret is not UNSET:
                entity.secret = secret
            if temp_secret is not UNSET:
                entity.temp_secret = temp_secret
            if recovery_codes is not UNSET:
                entity.recovery_codes = recovery_codes
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(entity, "recovery_codes")

        await session.commit()
        await session.refresh(entity)
        return entity
