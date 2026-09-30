import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import OutboxEvent
from app.models.user import User
from app.models.user_profile import UserProfile


@pytest.mark.asyncio
async def test_register_profile_success(client: AsyncClient, db_session: AsyncSession, auth_headers: dict[str, str]):
    payload = {
        "username": "cyber_knight",
        "bio": "Defender of open source and virtual worlds.",
        "avatar_url": "https://cdn.discordia.app/avatars/knight.png",
    }

    response = await client.post("/api/v1/users/me", json=payload, headers=auth_headers)

    assert response.status_code == 201
    data = response.json()
    assert data["user_id"] == auth_headers["X-User-Id"]
    assert data["username"] == "cyber_knight"
    assert data["bio"] == "Defender of open source and virtual worlds."
    assert data["avatar_url"] == "https://cdn.discordia.app/avatars/knight.png"
    assert data["activity_status"] == "offline"
    assert data["custom_status"] is None
    assert "created_at" in data

    # Verify DB persistence of User and Profile
    user_res = await db_session.execute(select(User).where(User.id == auth_headers["X-User-Id"]))
    user = user_res.scalar_one_or_none()
    assert user is not None
    assert user.email == auth_headers["X-User-Email"]
    assert user.is_active is True
    assert user.is_suspended is False

    profile_res = await db_session.execute(select(UserProfile).where(UserProfile.user_id == auth_headers["X-User-Id"]))
    profile = profile_res.scalar_one_or_none()
    assert profile is not None
    assert profile.username == "cyber_knight"

    # Verify Transactional Outbox event
    outbox_res = await db_session.execute(
        select(OutboxEvent).where(
            OutboxEvent.aggregate_id == auth_headers["X-User-Id"],
            OutboxEvent.event_type == "user.registered",
        )
    )
    event = outbox_res.scalar_one_or_none()
    assert event is not None
    assert event.aggregate_type == "user"
    assert event.payload["user_id"] == auth_headers["X-User-Id"]
    assert event.payload["username"] == "cyber_knight"
    assert event.payload["email"] == auth_headers["X-User-Email"]


@pytest.mark.asyncio
async def test_register_profile_missing_user_id(client: AsyncClient):
    payload = {"username": "valid_user"}
    headers = {"X-User-Email": "user@discordia.com"}

    response = await client.post("/api/v1/users/me", json=payload, headers=headers)

    assert response.status_code == 401
    data = response.json()
    assert data["status"] == 401
    assert "Unauthenticated" in data["detail"]


@pytest.mark.asyncio
async def test_register_profile_missing_email(client: AsyncClient):
    payload = {"username": "valid_user"}
    headers = {"X-User-Id": "auth0|some-user-id"}

    response = await client.post("/api/v1/users/me", json=payload, headers=headers)

    assert response.status_code == 400
    data = response.json()
    assert data["status"] == 400
    assert "email is required" in data["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "verified_header",
    [
        None,  # Gateway did not propagate the flag (e.g. Auth0 Action missing the claim)
        "false",
        "",
        "1",  # only the literal "true" is accepted: fail closed on anything ambiguous
        "yes",
    ],
)
async def test_register_profile_unverified_email_forbidden(
    client: AsyncClient, db_session: AsyncSession, verified_header: str | None
):
    headers = {"X-User-Id": "auth0|unverified-user", "X-User-Email": "victim@discordia.com"}
    if verified_header is not None:
        headers["X-User-Email-Verified"] = verified_header

    response = await client.post("/api/v1/users/me", json={"username": "squatter"}, headers=headers)

    assert response.status_code == 403
    assert response.headers["content-type"] == "application/problem+json"
    data = response.json()
    assert data["status"] == 403
    assert data["type"] == "https://discordia.app/problems/email-not-verified"
    assert "must be verified" in data["detail"]

    # Nothing may be persisted: the email must stay free for its real owner.
    user = (await db_session.execute(select(User).where(User.email == "victim@discordia.com"))).scalar_one_or_none()
    assert user is None
    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    assert events == []


@pytest.mark.asyncio
async def test_register_profile_verified_header_is_case_insensitive(client: AsyncClient):
    headers = {
        "X-User-Id": "auth0|case-user",
        "X-User-Email": "case@discordia.com",
        "X-User-Email-Verified": "True",
    }
    response = await client.post("/api/v1/users/me", json={"username": "case_user"}, headers=headers)
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_unverified_user_blocked_email_is_still_available_for_owner(client: AsyncClient):
    """CA2 guard: a squatting attempt with an unverified email must not block the legitimate owner."""
    squatter = {"X-User-Id": "auth0|squatter", "X-User-Email": "owner@discordia.com", "X-User-Email-Verified": "false"}
    owner = {"X-User-Id": "auth0|owner", "X-User-Email": "owner@discordia.com", "X-User-Email-Verified": "true"}

    blocked = await client.post("/api/v1/users/me", json={"username": "squatter"}, headers=squatter)
    assert blocked.status_code == 403

    registered = await client.post("/api/v1/users/me", json={"username": "real_owner"}, headers=owner)
    assert registered.status_code == 201


@pytest.mark.asyncio
async def test_get_my_profile_does_not_require_verified_email(client: AsyncClient, auth_headers: dict[str, str]):
    """Verification gates provisioning only; reading an existing profile must keep working."""
    created = await client.post("/api/v1/users/me", json={"username": "reader"}, headers=auth_headers)
    assert created.status_code == 201

    headers = {"X-User-Id": auth_headers["X-User-Id"]}
    res = await client.get("/api/v1/users/me", headers=headers)
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_register_profile_duplicate_user_id_conflict(client: AsyncClient, auth_headers: dict[str, str]):
    payload = {"username": "first_user"}
    first_res = await client.post("/api/v1/users/me", json=payload, headers=auth_headers)
    assert first_res.status_code == 201

    duplicate_res = await client.post("/api/v1/users/me", json={"username": "second_user"}, headers=auth_headers)
    assert duplicate_res.status_code == 201
    data = duplicate_res.json()
    assert data["username"] == "first_user"



@pytest.mark.asyncio
async def test_register_profile_duplicate_username_conflict(client: AsyncClient, auth_headers: dict[str, str]):
    # User 1 registers username "unique_tag"
    res1 = await client.post("/api/v1/users/me", json={"username": "unique_tag"}, headers=auth_headers)
    assert res1.status_code == 201

    # User 2 tries to register the same username
    user2_headers = {
        "X-User-Id": "auth0|user-2",
        "X-User-Email": "other@discordia.com",
        "X-User-Email-Verified": "true",
    }
    res2 = await client.post("/api/v1/users/me", json={"username": "unique_tag"}, headers=user2_headers)
    assert res2.status_code == 409
    data = res2.json()
    assert data["status"] == 409
    assert "already in use" in data["detail"]


@pytest.mark.asyncio
async def test_register_profile_validation_invalid_username(client: AsyncClient, auth_headers: dict[str, str]):
    # Too short (< 3 chars)
    res_short = await client.post("/api/v1/users/me", json={"username": "ab"}, headers=auth_headers)
    assert res_short.status_code == 422

    # Invalid characters (spaces, special characters)
    res_invalid_chars = await client.post(
        "/api/v1/users/me", json={"username": "invalid name with spaces!"}, headers=auth_headers
    )
    assert res_invalid_chars.status_code == 422


@pytest.mark.asyncio
async def test_register_profile_validation_null_bytes(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.post(
        "/api/v1/users/me", json={"username": "safe_name", "bio": "bad\x00byte"}, headers=auth_headers
    )
    assert res.status_code == 400
    data = res.json()
    assert "cannot contain null characters" in data["detail"]
