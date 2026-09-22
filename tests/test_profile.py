import uuid

import pytest
from sqlalchemy import delete

from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.models.user_profile import UserProfile

URL = "/api/v1/users/me/profile"


async def _create_user(username: str, bio: str | None = None) -> str:
    async with AsyncSessionLocal() as session:
        user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="hashed")
        user.profile = UserProfile(username=username, bio=bio)
        session.add(user)
        await session.commit()
        return user.id


async def _delete_users(*user_ids: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(User).where(User.id.in_(user_ids)))
        await session.commit()


def _unique(prefix: str = "user") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def user_id():
    uid = await _create_user(_unique())
    yield uid
    await _delete_users(uid)


def _headers(uid: str) -> dict:
    return {"X-User-Id": uid}

# CA 1: edición exitosa

async def test_update_username_and_bio(client, user_id):
    new_name = _unique("nuevo")
    response = await client.patch(URL, json={"username": new_name, "bio": "  Hola!  "}, headers=_headers(user_id))

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == user_id
    assert body["username"] == new_name
    assert body["bio"] == "Hola!"


async def test_update_persists_in_db(client, user_id):
    new_name = _unique("persist")
    await client.patch(URL, json={"username": new_name}, headers=_headers(user_id))

    async with AsyncSessionLocal() as session:
        profile = await session.get(UserProfile, user_id)
        assert profile.username == new_name


async def test_partial_update_keeps_other_fields(client):
    original = _unique("orig")
    uid = await _create_user(original, bio="bio original")
    try:
        response = await client.patch(URL, json={"bio": "bio nueva"}, headers=_headers(uid))
        assert response.status_code == 200
        assert response.json()["username"] == original
        assert response.json()["bio"] == "bio nueva"
    finally:
        await _delete_users(uid)


async def test_bio_null_or_blank_clears_bio(client):
    uid = await _create_user(_unique(), bio="algo")
    try:
        response = await client.patch(URL, json={"bio": "   "}, headers=_headers(uid))
        assert response.status_code == 200
        assert response.json()["bio"] is None
    finally:
        await _delete_users(uid)


async def test_keeping_same_username_is_ok(client):
    name = _unique("same")
    uid = await _create_user(name)
    try:
        response = await client.patch(URL, json={"username": name, "bio": "x"}, headers=_headers(uid))
        assert response.status_code == 200
    finally:
        await _delete_users(uid)

# CA 3: datos inválidos

@pytest.mark.parametrize(
    "payload",
    [
        {"username": "ab"},
        {"username": "a" * 33},
        {"username": "con espacios"},
        {"username": "emoji😀"},
        {"username": None},
        {"bio": "x" * 191},
        {},
        {"email": "otro@example.com"},
    ],
)
async def test_invalid_data_returns_422_and_does_not_persist(client, user_id, payload):
    async with AsyncSessionLocal() as session:
        before = (await session.get(UserProfile, user_id)).username

    response = await client.patch(URL, json=payload, headers=_headers(user_id))

    assert response.status_code == 422
    async with AsyncSessionLocal() as session:
        assert (await session.get(UserProfile, user_id)).username == before


async def test_username_already_taken_returns_409(client, user_id):
    other_name = _unique("taken")
    other_id = await _create_user(other_name)
    try:
        response = await client.patch(URL, json={"username": other_name}, headers=_headers(user_id))
        assert response.status_code == 409
    finally:
        await _delete_users(other_id)


# Autenticacion

async def test_missing_user_header_returns_401(client):
    response = await client.patch(URL, json={"bio": "hola"})
    assert response.status_code == 401

async def test_unknown_user_returns_404(client):
    response = await client.patch(URL, json={"bio": "hola"}, headers=_headers(str(uuid.uuid4())))
    assert response.status_code == 404

async def test_explicit_null_bio_clears_bio(client):
    uid = await _create_user(_unique(), bio="algo")
    try:
        response = await client.patch(URL, json={"bio": None}, headers=_headers(uid))
        assert response.status_code == 200
        assert response.json()["bio"] is None
    finally:
        await _delete_users(uid)


async def test_username_race_condition_returns_409(client, user_id, monkeypatch):
    from app.repositories.profile_repository import ProfileRepository

    other_name = _unique("race")
    other_id = await _create_user(other_name)

    async def not_found(self, username):
        return None

    monkeypatch.setattr(ProfileRepository, "get_by_username", not_found)
    try:
        response = await client.patch(URL, json={"username": other_name}, headers=_headers(user_id))
        assert response.status_code == 409
    finally:
        await _delete_users(other_id)
