import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.password_reset import get_password_reset_service
from app.clients.auth0 import Auth0PasswordResetClient
from app.exceptions import IdentityProviderUnavailableError
from app.main import app as fastapi_app
from app.models.password_reset_request import PasswordResetRequest
from app.schemas.password_reset import GENERIC_RESET_MESSAGE
from app.services.password_reset_service import PasswordResetService, hash_email

URL = "/api/v1/auth/password-reset"
MAX_REQUESTS = 3
WINDOW_SECONDS = 900
SECRET_DETAIL = "auth0 said: tenant dev-secret connection Username-Password-Authentication"


class FakeSender:
    def __init__(self):
        self.calls: list[str] = []
        self.fail = False

    async def request_password_reset(self, email: str) -> None:
        self.calls.append(email)
        if self.fail:
            raise IdentityProviderUnavailableError()


class FakeClock:
    def __init__(self):
        self.now = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest_asyncio.fixture
async def reset_client(client: AsyncClient, sender: FakeSender, clock: FakeClock) -> AsyncGenerator[AsyncClient]:
    def service_override() -> PasswordResetService:
        return PasswordResetService(
            sender=sender, max_requests=MAX_REQUESTS, window_seconds=WINDOW_SECONDS, clock=clock
        )

    fastapi_app.dependency_overrides[get_password_reset_service] = service_override
    yield client


# CA1 / CA4


@pytest.mark.asyncio
async def test_request_is_accepted_and_forwarded_to_auth0(reset_client: AsyncClient, sender: FakeSender):
    response = await reset_client.post(URL, json={"email": "user@discordia.com"})

    assert response.status_code == 202
    assert response.json() == {"detail": GENERIC_RESET_MESSAGE}
    assert sender.calls == ["user@discordia.com"]


@pytest.mark.asyncio
async def test_registered_and_unregistered_emails_get_identical_responses(
    reset_client: AsyncClient, sender: FakeSender, auth_headers: dict[str, str]
):
    """CA4: the service never checks registration, so both cases are indistinguishable."""
    await reset_client.post("/api/v1/users/me", json={"username": "registered"}, headers=auth_headers)

    registered = await reset_client.post(URL, json={"email": auth_headers["X-User-Email"]})
    unknown = await reset_client.post(URL, json={"email": "nobody@discordia.com"})

    assert registered.status_code == unknown.status_code == 202
    assert registered.json() == unknown.json()
    assert sender.calls == [auth_headers["X-User-Email"], "nobody@discordia.com"]


@pytest.mark.asyncio
async def test_endpoint_is_public(reset_client: AsyncClient):
    """No X-User-* headers: the user who forgot the password has no session."""
    response = await reset_client.post(URL, json={"email": "user@discordia.com"})
    assert response.status_code == 202


@pytest.mark.asyncio
@pytest.mark.parametrize("email", ["not-an-email", "", "a@", "@discordia.com", "x" * 250 + "@d.com"])
async def test_invalid_email_is_rejected_without_calling_auth0(reset_client: AsyncClient, sender: FakeSender, email):
    response = await reset_client.post(URL, json={"email": email})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert sender.calls == []


# CA5


@pytest.mark.asyncio
async def test_fourth_request_in_window_is_throttled(reset_client: AsyncClient, sender: FakeSender, clock: FakeClock):
    for _ in range(MAX_REQUESTS):
        assert (await reset_client.post(URL, json={"email": "user@discordia.com"})).status_code == 202
        clock.advance(60)

    response = await reset_client.post(URL, json={"email": "user@discordia.com"})

    assert response.status_code == 429
    assert response.headers["content-type"] == "application/problem+json"
    data = response.json()
    assert data["type"] == "https://discordia.app/problems/password-reset-throttled"
    assert data["status"] == 429
    # Oldest request was 180 s ago: the window frees a slot in 900 - 180 s.
    assert response.headers["retry-after"] == str(WINDOW_SECONDS - 3 * 60)
    assert len(sender.calls) == MAX_REQUESTS


@pytest.mark.asyncio
async def test_throttle_key_ignores_case_and_whitespace(reset_client: AsyncClient, sender: FakeSender):
    for email in ["User@Discordia.com", "  user@discordia.com", "USER@DISCORDIA.COM"]:
        assert (await reset_client.post(URL, json={"email": email})).status_code == 202

    response = await reset_client.post(URL, json={"email": "user@discordia.com"})

    assert response.status_code == 429
    assert sender.calls == ["user@discordia.com"] * MAX_REQUESTS


@pytest.mark.asyncio
async def test_throttle_applies_to_unregistered_emails_too(reset_client: AsyncClient):
    """The 429 must not reveal registration: an unknown email is limited exactly like a known one."""
    for _ in range(MAX_REQUESTS):
        await reset_client.post(URL, json={"email": "nobody@discordia.com"})

    assert (await reset_client.post(URL, json={"email": "nobody@discordia.com"})).status_code == 429


@pytest.mark.asyncio
async def test_limit_is_per_email(reset_client: AsyncClient):
    for _ in range(MAX_REQUESTS):
        await reset_client.post(URL, json={"email": "first@discordia.com"})

    assert (await reset_client.post(URL, json={"email": "first@discordia.com"})).status_code == 429
    assert (await reset_client.post(URL, json={"email": "second@discordia.com"})).status_code == 202


@pytest.mark.asyncio
async def test_requests_are_allowed_again_after_the_window(
    reset_client: AsyncClient, sender: FakeSender, clock: FakeClock
):
    for _ in range(MAX_REQUESTS):
        await reset_client.post(URL, json={"email": "user@discordia.com"})
    assert (await reset_client.post(URL, json={"email": "user@discordia.com"})).status_code == 429

    clock.advance(WINDOW_SECONDS + 1)

    assert (await reset_client.post(URL, json={"email": "user@discordia.com"})).status_code == 202
    assert len(sender.calls) == MAX_REQUESTS + 1


@pytest.mark.asyncio
async def test_expired_rows_are_purged(reset_client: AsyncClient, db_session: AsyncSession, clock: FakeClock):
    await reset_client.post(URL, json={"email": "old@discordia.com"})
    clock.advance(WINDOW_SECONDS + 1)
    await reset_client.post(URL, json={"email": "new@discordia.com"})

    rows = (await db_session.execute(select(PasswordResetRequest))).scalars().all()
    assert [row.email_hash for row in rows] == [hash_email("new@discordia.com")]


@pytest.mark.asyncio
async def test_email_is_stored_hashed(reset_client: AsyncClient, db_session: AsyncSession):
    await reset_client.post(URL, json={"email": "private@discordia.com"})

    row = (await db_session.execute(select(PasswordResetRequest))).scalar_one()
    assert row.email_hash == hash_email("private@discordia.com")
    assert len(row.email_hash) == 64
    assert "private" not in row.email_hash


# Auth0 failures


@pytest.mark.asyncio
async def test_auth0_failure_returns_generic_503(reset_client: AsyncClient, sender: FakeSender):
    sender.fail = True

    response = await reset_client.post(URL, json={"email": "user@discordia.com"})

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert "auth0" not in response.text.lower()


@pytest.mark.asyncio
async def test_failed_attempts_still_count_toward_the_limit(reset_client: AsyncClient, sender: FakeSender):
    sender.fail = True
    for _ in range(MAX_REQUESTS):
        assert (await reset_client.post(URL, json={"email": "user@discordia.com"})).status_code == 503

    sender.fail = False
    assert (await reset_client.post(URL, json={"email": "user@discordia.com"})).status_code == 429


# Auth0 client


def _auth0_client(handler) -> Auth0PasswordResetClient:
    return Auth0PasswordResetClient(
        domain="tenant.auth0.com",
        client_id="public-client-id",
        connection="Username-Password-Authentication",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_auth0_client_calls_change_password_endpoint():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="We've just sent you an email to reset your password.")

    await _auth0_client(handler).request_password_reset("user@discordia.com")

    assert len(seen) == 1
    assert str(seen[0].url) == "https://tenant.auth0.com/dbconnections/change_password"
    assert seen[0].method == "POST"
    assert json.loads(seen[0].content) == {
        "client_id": "public-client-id",
        "email": "user@discordia.com",
        "connection": "Username-Password-Authentication",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 429, 500])
async def test_auth0_client_raises_on_error_status(status_code: int):
    client = _auth0_client(lambda request: httpx.Response(status_code, text=SECRET_DETAIL))
    with pytest.raises(IdentityProviderUnavailableError) as exc_info:
        await client.request_password_reset("user@discordia.com")
    assert SECRET_DETAIL not in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_auth0_client_raises_on_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    with pytest.raises(IdentityProviderUnavailableError):
        await _auth0_client(handler).request_password_reset("user@discordia.com")


@pytest.mark.asyncio
async def test_auth0_client_misconfigured_fails_without_network():
    client = Auth0PasswordResetClient(domain="", client_id="", connection="Username-Password-Authentication")
    with pytest.raises(IdentityProviderUnavailableError):
        await client.request_password_reset("user@discordia.com")
