import time
from collections.abc import Callable
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.logger import get_logger
from app.exceptions import IdentityProviderUnavailableError

logger = get_logger(__name__)

# Renovar el token de la Management API un minuto antes de que venza
TOKEN_EXPIRY_MARGIN_SECONDS = 60


class Auth0ManagementClient:
    """Blocks and unblocks Auth0 users (PATCH /api/v2/users/{id} with {"blocked": ...}), ADR-002.

    A blocked user cannot log in nor get new tokens (silent auth included). Uses a Machine to Machine
    application (client credentials) with read:users and update:users on the Management API. The token
    is cached in memory until shortly before it expires.
    """

    def __init__(
        self,
        domain: str,
        client_id: str,
        client_secret: str,
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._domain = domain
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout_seconds
        self._transport = transport
        self._clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    async def _access_token(self) -> str:
        if self._token and self._clock() < self._token_expires_at:
            return self._token
        if not self._domain or not self._client_id or not self._client_secret:
            logger.error("auth0_management_misconfigured", missing="AUTH0_MGMT_CLIENT_ID/AUTH0_MGMT_CLIENT_SECRET")
            raise IdentityProviderUnavailableError()

        payload = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "audience": f"https://{self._domain}/api/v2/",
        }
        try:
            async with self._http() as client:
                response = await client.post(f"https://{self._domain}/oauth/token", json=payload)
        except httpx.HTTPError as exc:
            logger.error("auth0_management_token_unreachable", error_type=type(exc).__name__)
            raise IdentityProviderUnavailableError() from exc

        if response.status_code >= 400:
            logger.error("auth0_management_token_rejected", status_code=response.status_code)
            raise IdentityProviderUnavailableError()

        data = response.json()
        self._token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        self._token_expires_at = self._clock() + max(expires_in - TOKEN_EXPIRY_MARGIN_SECONDS, 0)
        return self._token

    async def set_blocked(self, user_id: str, blocked: bool) -> None:
        """Blocks or unblocks one Auth0 identity. An identity unknown to Auth0 is skipped, not an error."""
        token = await self._access_token()
        url = f"https://{self._domain}/api/v2/users/{quote(user_id, safe='')}"
        try:
            async with self._http() as client:
                response = await client.patch(
                    url, json={"blocked": blocked}, headers={"Authorization": f"Bearer {token}"}
                )
        except httpx.HTTPError as exc:
            logger.error("auth0_block_unreachable", error_type=type(exc).__name__)
            raise IdentityProviderUnavailableError() from exc

        if response.status_code == 404:
            # Un alias que ya no existe en Auth0 (cuenta federada borrada): no hay nada que bloquear
            logger.warning("auth0_block_user_not_found", user_id=user_id)
            return
        if response.status_code >= 400:
            logger.error("auth0_block_rejected", status_code=response.status_code, user_id=user_id)
            raise IdentityProviderUnavailableError()


_management_client: Auth0ManagementClient | None = None


def get_auth0_management_client() -> Auth0ManagementClient:
    """One instance per process, so the Management API token is reused between requests."""
    global _management_client
    if _management_client is None:
        _management_client = Auth0ManagementClient(
            domain=settings.auth0_domain,
            client_id=settings.auth0_mgmt_client_id,
            client_secret=settings.auth0_mgmt_client_secret,
            timeout_seconds=settings.auth0_timeout_seconds,
        )
    return _management_client
