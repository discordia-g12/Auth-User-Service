from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin_users import get_suspension_service
from app.exceptions import IdentityProviderUnavailableError, SuspensionDenylistUnavailableError
from app.main import app as fastapi_app
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.models.user_profile import UserProfile
from app.services.suspension_service import SuspensionService

SUSPEND_URL = "/api/v1/admin/users/suspensions"
SUSPENDED_URL = "/api/v1/admin/users/suspended"
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)

STAFF_ID = "auth0|staff-1"
STAFF_HEADERS = {
    "X-User-Id": STAFF_ID,
    "X-User-Email": "staff@discordia.lol",
    "X-User-Email-Verified": "true",
    "X-User-Role": "staff",
}
USER_HEADERS = {**STAFF_HEADERS, "X-User-Role": "user"}


class FakeBlocker:
    def __init__(self):
        self.calls: list[tuple[str, bool]] = []
        self.fail = False

    async def set_blocked(self, user_id: str, blocked: bool) -> None:
        if self.fail:
            raise IdentityProviderUnavailableError()
        self.calls.append((user_id, blocked))


class FakeDenylist:
    def __init__(self):
        self.added: list[tuple[list[str], str]] = []
        self.removed: list[tuple[list[str], str]] = []
        self.fail = False

    async def add(self, user_ids: list[str], email: str) -> None:
        if self.fail:
            raise SuspensionDenylistUnavailableError()
        self.added.append((user_ids, email))

    async def remove(self, user_ids: list[str], email: str) -> None:
        if self.fail:
            raise SuspensionDenylistUnavailableError()
        self.removed.append((user_ids, email))


@pytest.fixture
def blocker() -> FakeBlocker:
    return FakeBlocker()


@pytest.fixture
def denylist() -> FakeDenylist:
    return FakeDenylist()


@pytest_asyncio.fixture
async def admin_client(
    client: AsyncClient, blocker: FakeBlocker, denylist: FakeDenylist
) -> AsyncGenerator[AsyncClient]:
    fastapi_app.dependency_overrides[get_suspension_service] = lambda: SuspensionService(
        blocker=blocker, denylist=denylist, clock=lambda: NOW
    )
    yield client


async def _create_user(db: AsyncSession, user_id: str, username: str, email: str, suspended: bool = False) -> None:
    db.add(
        User(id=user_id, email=email, is_active=True, is_suspended=suspended, suspended_at=NOW if suspended else None)
    )
    db.add(
        UserProfile(
            user_id=user_id, username=username, display_name=username.title(), bio="hola", avatar_url="https://x/a.png"
        )
    )
    await db.commit()


async def _get_user(db: AsyncSession, user_id: str) -> User:
    db.expire_all()
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one()


async def _events(db: AsyncSession, event_type: str) -> list[OutboxEvent]:
    result = await db.execute(select(OutboxEvent).where(OutboxEvent.event_type == event_type))
    return list(result.scalars().all())


# CA 1: suspensión exitosa


@pytest.mark.asyncio
async def test_staff_suspends_by_email(admin_client, db_session, blocker, denylist):
    await _create_user(db_session, "auth0|u1", "tomasv", "Tomas@Mail.com")

    response = await admin_client.post(
        SUSPEND_URL, json={"user": "tomas@mail.com", "reason": "spam reiterado"}, headers=STAFF_HEADERS
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == "auth0|u1"
    assert body["is_suspended"] is True
    assert body["suspension_reason"] == "spam reiterado"
    assert body["suspended_by"] == STAFF_ID

    user = await _get_user(db_session, "auth0|u1")
    assert user.is_suspended is True
    assert user.suspension_reason == "spam reiterado"
    assert blocker.calls == [("auth0|u1", True)]
    assert denylist.added == [(["auth0|u1"], "Tomas@Mail.com")]

    [event] = await _events(db_session, "user.suspended")
    assert event.aggregate_id == "auth0|u1"
    assert event.payload["identities"] == ["auth0|u1"]
    assert event.payload["reason"] == "spam reiterado"


@pytest.mark.asyncio
async def test_staff_suspends_by_username(admin_client, db_session):
    await _create_user(db_session, "auth0|u2", "lupaz", "lucia@mail.com")

    response = await admin_client.post(SUSPEND_URL, json={"user": "@lupaz", "reason": "acoso"}, headers=STAFF_HEADERS)

    assert response.status_code == 201
    assert response.json()["username"] == "lupaz"


@pytest.mark.asyncio
async def test_suspension_blocks_every_linked_identity(admin_client, db_session, blocker, denylist):
    await _create_user(db_session, "auth0|u3", "mgil", "martin@mail.com")
    db_session.add(
        OutboxEvent(
            aggregate_type="user_identity_alias",
            aggregate_id="google-oauth2|99",
            event_type="user.identity_linked",
            payload={"primary_user_id": "auth0|u3"},
            processed_at=NOW,
        )
    )
    await db_session.commit()

    response = await admin_client.post(SUSPEND_URL, json={"user": "auth0|u3", "reason": "x"}, headers=STAFF_HEADERS)

    assert response.status_code == 201
    assert blocker.calls == [("auth0|u3", True), ("google-oauth2|99", True)]
    assert denylist.added == [(["auth0|u3", "google-oauth2|99"], "martin@mail.com")]


@pytest.mark.asyncio
async def test_suspended_account_cannot_load_its_profile(client, db_session):
    await _create_user(db_session, "auth0|u4", "sofi", "sofi@mail.com", suspended=True)
    headers = {"X-User-Id": "auth0|u4", "X-User-Email": "sofi@mail.com", "X-User-Email-Verified": "true"}

    response = await client.get("/api/v1/users/me", headers=headers)

    assert response.status_code == 403
    assert response.json()["type"].endswith("/account-suspended")


@pytest.mark.asyncio
async def test_suspended_public_profile_is_not_available(client, db_session):
    await _create_user(db_session, "auth0|u5", "pepe", "pepe@mail.com", suspended=True)

    response = await client.post(
        "/api/v1/users/bulk", json={"user_ids": ["auth0|u5"]}, headers={"X-User-Id": "auth0|other"}
    )

    [profile] = response.json()
    assert profile["is_suspended"] is True
    assert profile["username"] == "pepe"  # los mensajes viejos siguen mostrando quién los escribió
    assert profile["avatar_url"] is None
    assert profile["bio"] is None


# CA 3: sin permisos


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [USER_HEADERS, {"X-User-Id": "auth0|x"}])
async def test_non_staff_cannot_suspend(admin_client, db_session, blocker, headers):
    await _create_user(db_session, "auth0|u6", "ana", "ana@mail.com")

    response = await admin_client.post(SUSPEND_URL, json={"user": "ana@mail.com", "reason": "x"}, headers=headers)

    assert response.status_code == 403
    assert response.json()["type"].endswith("/staff-only")
    assert blocker.calls == []
    assert (await _get_user(db_session, "auth0|u6")).is_suspended is False


@pytest.mark.asyncio
async def test_suspend_requires_identity(admin_client):
    response = await admin_client.post(SUSPEND_URL, json={"user": "a@b.com", "reason": "x"})

    assert response.status_code == 401


# Errores


@pytest.mark.asyncio
async def test_unknown_account_is_404(admin_client):
    response = await admin_client.post(
        SUSPEND_URL, json={"user": "nadie@mail.com", "reason": "x"}, headers=STAFF_HEADERS
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_already_suspended_is_409(admin_client, db_session, blocker):
    await _create_user(db_session, "auth0|u7", "beto", "beto@mail.com", suspended=True)

    response = await admin_client.post(SUSPEND_URL, json={"user": "@beto", "reason": "x"}, headers=STAFF_HEADERS)

    assert response.status_code == 409
    assert blocker.calls == []


@pytest.mark.asyncio
async def test_staff_cannot_suspend_themselves(admin_client, db_session):
    await _create_user(db_session, STAFF_ID, "staffer", "staff@discordia.lol")

    response = await admin_client.post(SUSPEND_URL, json={"user": "@staffer", "reason": "x"}, headers=STAFF_HEADERS)

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_reason_is_required(admin_client):
    response = await admin_client.post(SUSPEND_URL, json={"user": "@x", "reason": ""}, headers=STAFF_HEADERS)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_auth0_failure_changes_nothing(admin_client, db_session, blocker, denylist):
    await _create_user(db_session, "auth0|u8", "caro", "caro@mail.com")
    blocker.fail = True

    response = await admin_client.post(SUSPEND_URL, json={"user": "@caro", "reason": "x"}, headers=STAFF_HEADERS)

    assert response.status_code == 503
    assert denylist.added == []
    assert (await _get_user(db_session, "auth0|u8")).is_suspended is False
    assert await _events(db_session, "user.suspended") == []


@pytest.mark.asyncio
async def test_denylist_failure_changes_nothing_in_the_database(admin_client, db_session, denylist):
    await _create_user(db_session, "auth0|u9", "dani", "dani@mail.com")
    denylist.fail = True

    response = await admin_client.post(SUSPEND_URL, json={"user": "@dani", "reason": "x"}, headers=STAFF_HEADERS)

    assert response.status_code == 503
    assert (await _get_user(db_session, "auth0|u9")).is_suspended is False
    assert await _events(db_session, "user.suspended") == []


# Reactivar y listar


@pytest.mark.asyncio
async def test_staff_reactivates_a_suspended_account(admin_client, db_session, blocker, denylist):
    await _create_user(db_session, "auth0|u10", "eli", "eli@mail.com", suspended=True)

    response = await admin_client.delete("/api/v1/admin/users/auth0|u10/suspension", headers=STAFF_HEADERS)

    assert response.status_code == 200
    assert response.json()["is_suspended"] is False
    user = await _get_user(db_session, "auth0|u10")
    assert user.is_suspended is False
    assert user.suspended_at is None
    assert blocker.calls == [("auth0|u10", False)]
    assert denylist.removed == [(["auth0|u10"], "eli@mail.com")]
    assert len(await _events(db_session, "user.reactivated")) == 1


@pytest.mark.asyncio
async def test_reactivating_an_active_account_is_409(admin_client, db_session):
    await _create_user(db_session, "auth0|u11", "fede", "fede@mail.com")

    response = await admin_client.delete("/api/v1/admin/users/auth0|u11/suspension", headers=STAFF_HEADERS)

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_reactivating_unknown_account_is_404(admin_client):
    response = await admin_client.delete("/api/v1/admin/users/auth0|nope/suspension", headers=STAFF_HEADERS)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_non_staff_cannot_reactivate(admin_client, db_session):
    await _create_user(db_session, "auth0|u12", "gabi", "gabi@mail.com", suspended=True)

    response = await admin_client.delete("/api/v1/admin/users/auth0|u12/suspension", headers=USER_HEADERS)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_staff_lists_suspended_accounts(admin_client, db_session):
    await _create_user(db_session, "auth0|u13", "hugo", "hugo@mail.com", suspended=True)
    await _create_user(db_session, "auth0|u14", "ines", "ines@mail.com")

    response = await admin_client.get(SUSPENDED_URL, headers=STAFF_HEADERS)

    assert response.status_code == 200
    assert [u["username"] for u in response.json()] == ["hugo"]


@pytest.mark.asyncio
async def test_non_staff_cannot_list_suspended_accounts(admin_client):
    response = await admin_client.get(SUSPENDED_URL, headers=USER_HEADERS)

    assert response.status_code == 403
