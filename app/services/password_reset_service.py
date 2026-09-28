import hashlib
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.exceptions import PasswordResetThrottledError
from app.repositories.password_reset_repository import PasswordResetRepository

logger = get_logger(__name__)


class PasswordResetSender(Protocol):
    async def request_password_reset(self, email: str) -> None: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_email(email: str) -> str:
    return hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class PasswordResetService:
    """Password reset requests with a per-email rate limit.

    The service never checks whether the email is registered: every accepted request is
    forwarded to Auth0 and answered the same way. The limit applies to any email for
    the same reason: a 429 says nothing about whether an account exists.
    """

    def __init__(
        self,
        sender: PasswordResetSender,
        max_requests: int,
        window_seconds: int,
        repository: PasswordResetRepository | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ):
        self._sender = sender
        self._max_requests = max_requests
        self._window = timedelta(seconds=window_seconds)
        self._repository = repository or PasswordResetRepository()
        self._clock = clock

    async def request_reset(self, session: AsyncSession, email: str) -> None:
        email = normalize_email(email)
        email_hash = hash_email(email)
        now = self._clock()
        window_start = now - self._window

        await self._repository.purge_older_than(session, window_start)
        count, oldest = await self._repository.recent_requests(session, email_hash, window_start)

        if count >= self._max_requests:
            await session.commit()
            retry_after = self._retry_after_seconds(now, oldest)
            logger.warning("password_reset_throttled", email_hash=email_hash[:12], retry_after=retry_after)
            raise PasswordResetThrottledError(retry_after)

        await self._repository.add(session, email_hash, now)
        await session.commit()

        await self._sender.request_password_reset(email)
        logger.info("password_reset_requested", email_hash=email_hash[:12])

    def _retry_after_seconds(self, now: datetime, oldest: datetime | None) -> int:
        if oldest is None:
            return math.ceil(self._window.total_seconds())
        remaining = (_as_utc(oldest) + self._window - now).total_seconds()
        return max(1, math.ceil(remaining))
