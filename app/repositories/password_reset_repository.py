from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.password_reset_request import PasswordResetRequest


class PasswordResetRepository:
    async def purge_older_than(self, session: AsyncSession, cutoff: datetime) -> None:
        await session.execute(delete(PasswordResetRequest).where(PasswordResetRequest.requested_at < cutoff))

    async def recent_requests(
        self, session: AsyncSession, email_hash: str, since: datetime
    ) -> tuple[int, datetime | None]:
        """Returns how many requests the email made since `since`, and when the oldest of them was."""
        stmt = select(func.count(PasswordResetRequest.id), func.min(PasswordResetRequest.requested_at)).where(
            PasswordResetRequest.email_hash == email_hash,
            PasswordResetRequest.requested_at >= since,
        )
        count, oldest = (await session.execute(stmt)).one()
        return count, oldest

    async def add(self, session: AsyncSession, email_hash: str, requested_at: datetime) -> None:
        session.add(PasswordResetRequest(email_hash=email_hash, requested_at=requested_at))
