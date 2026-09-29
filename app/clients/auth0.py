import httpx

from app.core.config import settings
from app.core.logger import get_logger
from app.exceptions import IdentityProviderUnavailableError

logger = get_logger(__name__)


class Auth0PasswordResetClient:
    """Triggers Auth0's interactive password reset (POST /dbconnections/change_password).

    Auth0 sends the email with a single-use link and hosts the page where the new password is
    chosen, so Discordia never handles the password itself. Auth0 answers 200
    whether or not the email is registered, so this call cannot be used to enumerate accounts.
    """

    def __init__(
        self,
        domain: str,
        client_id: str,
        connection: str,
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._domain = domain
        self._client_id = client_id
        self._connection = connection
        self._timeout = timeout_seconds
        self._transport = transport

    async def request_password_reset(self, email: str) -> None:
        if not self._domain or not self._client_id:
            logger.error("auth0_password_reset_misconfigured", missing="AUTH0_DOMAIN/AUTH0_CLIENT_ID")
            raise IdentityProviderUnavailableError()

        url = f"https://{self._domain}/dbconnections/change_password"
        payload = {"client_id": self._client_id, "email": email, "connection": self._connection}
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            logger.error("auth0_password_reset_unreachable", error_type=type(exc).__name__)
            raise IdentityProviderUnavailableError() from exc

        if response.status_code >= 400:
            logger.error("auth0_password_reset_rejected", status_code=response.status_code)
            raise IdentityProviderUnavailableError()


def build_auth0_password_reset_client() -> Auth0PasswordResetClient:
    return Auth0PasswordResetClient(
        domain=settings.auth0_domain,
        client_id=settings.auth0_client_id,
        connection=settings.auth0_db_connection,
        timeout_seconds=settings.auth0_timeout_seconds,
    )
