from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.logger import get_logger
from app.exceptions import SuspensionDenylistUnavailableError

logger = get_logger(__name__)

# Mismo formato que lee Gateway/auth0_validator.lua (is_suspended). Si cambia acá, cambia allá.
KEY_PREFIX = "suspended:"


def identity_key(user_id: str) -> str:
    return f"{KEY_PREFIX}sub:{user_id}"


def email_key(email: str) -> str:
    return f"{KEY_PREFIX}email:{email.strip().lower()}"


class SuspensionDenylist:
    """Suspended accounts in the Gateway's Redis: Kong answers 403 even with a token that is still valid.

    - One key per Auth0 identity (primary user id and federated aliases), with a TTL equal to the access
      token lifetime: after that no token issued before the suspension is valid, and Auth0 (blocked user)
      does not issue new ones.
    - One key per email, without TTL until reactivation: covers a new federated identity with the same
      email, which Auth0 does not know is suspended.
    """

    def __init__(self, redis: Redis, ttl_seconds: int):
        self._redis = redis
        self._ttl = ttl_seconds

    async def add(self, user_ids: list[str], email: str) -> None:
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                for user_id in user_ids:
                    pipe.set(identity_key(user_id), "1", ex=self._ttl)
                pipe.set(email_key(email), "1")
                await pipe.execute()
        except (RedisError, OSError) as exc:
            logger.error("suspension_denylist_unavailable", operation="add", error_type=type(exc).__name__)
            raise SuspensionDenylistUnavailableError() from exc

    async def remove(self, user_ids: list[str], email: str) -> None:
        try:
            await self._redis.delete(*[identity_key(user_id) for user_id in user_ids], email_key(email))
        except (RedisError, OSError) as exc:
            logger.error("suspension_denylist_unavailable", operation="remove", error_type=type(exc).__name__)
            raise SuspensionDenylistUnavailableError() from exc


_denylist: SuspensionDenylist | None = None


def get_suspension_denylist() -> SuspensionDenylist:
    """One connection pool per process."""
    global _denylist
    if _denylist is None:
        redis = Redis(
            host=settings.gateway_redis_host,
            port=settings.gateway_redis_port,
            socket_timeout=settings.gateway_redis_timeout_seconds,
            socket_connect_timeout=settings.gateway_redis_timeout_seconds,
        )
        _denylist = SuspensionDenylist(redis, settings.suspension_denylist_ttl_seconds)
    return _denylist
