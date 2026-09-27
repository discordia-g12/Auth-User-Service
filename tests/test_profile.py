import io
import uuid

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import OutboxEvent
from app.models.user import User
from app.models.user_profile import UserProfile

URL_PROFILE = "/api/v1/users/me/profile"
URL_AVATAR = "/api/v1/users/me/profile/avatar"


# Helpers compartidos. Usan db_session (SQLite en memoria, fixture de conftest.py)
# en vez de conectarse a Postgres real: mas rapido, aislado, y no depende de Docker.

def _unique(prefix: str = "user") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _headers(uid: str) -> dict:
    return {"X-User-Id": uid}


def _fake_image_bytes(fmt: str = "PNG") -> bytes:
    """Genera una imagen valida en memoria, sin depender de un archivo en disco."""
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10), color="blue").save(buffer, format=fmt)
    return buffer.getvalue()


async def _create_user(db_session: AsyncSession, username: str, bio: str | None = None) -> str:
    """Inserta un User + UserProfile directo en la DB de test."""
    user_id = _unique("uid")
    user = User(id=user_id, email=f"{user_id}@example.com", is_active=True, is_suspended=False)
    user.profile = UserProfile(user_id=user_id, username=username, bio=bio)
    db_session.add(user)
    await db_session.commit()
    return user_id


@pytest.fixture
async def user_id(db_session: AsyncSession):
    return await _create_user(db_session, _unique())


@pytest.fixture(autouse=True)
def mock_cloudinary(monkeypatch):
    """Ningun test le pega a Cloudinary real: devolvemos una URL fake siempre."""

    def fake_upload(contents: bytes, user_id: str) -> str:
        return f"https://res.cloudinary.com/fake/avatars/{user_id}.png"

    monkeypatch.setattr("app.services.profile_service.cloudinary_upload_avatar", fake_upload)


# CA 1: Edicion exitosa (username / bio)

async def test_update_username_and_bio(client, db_session, user_id):
    new_name = _unique("nuevo")
    payload = {"username": new_name, "bio": "  Hola!  "}
    response = await client.patch(URL_PROFILE, json=payload, headers=_headers(user_id))

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == user_id
    assert body["username"] == new_name
    assert body["bio"] == "Hola!"


async def test_update_persists_in_db(client, db_session, user_id):
    new_name = _unique("persist")
    await client.patch(URL_PROFILE, json={"username": new_name}, headers=_headers(user_id))

    db_session.expire_all()
    profile = await db_session.get(UserProfile, user_id)
    assert profile.username == new_name


async def test_partial_update_keeps_other_fields(client, db_session):
    original = _unique("orig")
    uid = await _create_user(db_session, original, bio="bio original")

    response = await client.patch(URL_PROFILE, json={"bio": "bio nueva"}, headers=_headers(uid))
    assert response.status_code == 200
    assert response.json()["username"] == original
    assert response.json()["bio"] == "bio nueva"


async def test_bio_null_or_blank_clears_bio(client, db_session):
    uid = await _create_user(db_session, _unique(), bio="algo")

    response = await client.patch(URL_PROFILE, json={"bio": "   "}, headers=_headers(uid))
    assert response.status_code == 200
    assert response.json()["bio"] is None


async def test_keeping_same_username_is_ok(client, db_session):
    name = _unique("same")
    uid = await _create_user(db_session, name)

    response = await client.patch(URL_PROFILE, json={"username": name, "bio": "x"}, headers=_headers(uid))
    assert response.status_code == 200


async def test_explicit_null_bio_clears_bio(client, db_session):
    uid = await _create_user(db_session, _unique(), bio="algo")

    response = await client.patch(URL_PROFILE, json={"bio": None}, headers=_headers(uid))
    assert response.status_code == 200
    assert response.json()["bio"] is None


# CA 2: Foto de perfil actualizada (avatar via Cloudinary)

async def test_upload_avatar_success_updates_profile(client, db_session, user_id):
    files = {"file": ("avatar.png", _fake_image_bytes("PNG"), "image/png")}
    response = await client.patch(URL_AVATAR, files=files, headers=_headers(user_id))

    assert response.status_code == 200
    body = response.json()
    assert body["avatar_url"] == f"https://res.cloudinary.com/fake/avatars/{user_id}.png"

    profile = await db_session.get(UserProfile, user_id)
    db_session.expire(profile)
    await db_session.refresh(profile)
    assert profile.avatar_url == body["avatar_url"]


async def test_upload_avatar_accepts_jpeg_and_webp(client, db_session, user_id):
    for fmt, content_type in [("JPEG", "image/jpeg"), ("WEBP", "image/webp")]:
        files = {"file": (f"avatar.{fmt.lower()}", _fake_image_bytes(fmt), content_type)}
        response = await client.patch(URL_AVATAR, files=files, headers=_headers(user_id))
        assert response.status_code == 200


async def test_upload_avatar_emits_outbox_event(client, db_session, user_id):
    """CA 2 (se sube la imagen) + integracion con el patron Outbox / RabbitMQ."""
    files = {"file": ("avatar.png", _fake_image_bytes("PNG"), "image/png")}
    await client.patch(URL_AVATAR, files=files, headers=_headers(user_id))

    result = await db_session.execute(select(OutboxEvent).where(OutboxEvent.aggregate_id == user_id))
    events = result.scalars().all()

    assert len(events) == 1
    assert events[0].event_type == "user.profile.updated"
    assert events[0].aggregate_type == "user_profile"
    assert events[0].payload["avatar_url"].startswith("https://res.cloudinary.com/")
    assert events[0].processed_at is None


# CA 3: Datos invalidos (aplica tanto a username/bio como a la imagen)

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
async def test_invalid_data_returns_422_and_does_not_persist(client, db_session, user_id, payload):
    """CA 3 (texto): datos invalidos de username/bio no se persisten."""
    before = (await db_session.get(UserProfile, user_id)).username

    response = await client.patch(URL_PROFILE, json=payload, headers=_headers(user_id))

    assert response.status_code == 422
    db_session.expire_all()
    assert (await db_session.get(UserProfile, user_id)).username == before


async def test_upload_avatar_rejects_non_image_file(client, db_session, user_id):
    """CA 2 + CA 3: un archivo que no es imagen no se sube ni se persiste."""
    files = {"file": ("not_an_image.txt", b"esto no es una imagen", "text/plain")}
    response = await client.patch(URL_AVATAR, files=files, headers=_headers(user_id))

    assert response.status_code == 422

    profile = await db_session.get(UserProfile, user_id)
    assert profile.avatar_url is None


async def test_upload_avatar_rejects_disallowed_format(client, user_id):
    """CA 2 + CA 3: formato de imagen no permitido (ej. BMP)."""
    files = {"file": ("avatar.bmp", _fake_image_bytes("BMP"), "image/bmp")}
    response = await client.patch(URL_AVATAR, files=files, headers=_headers(user_id))
    assert response.status_code == 422


async def test_upload_avatar_rejects_oversized_file(client, user_id, monkeypatch):
    """CA 2 + CA 3: imagen que supera el limite de tamaño (ADR-02)."""
    from app.services import avatar_validator

    monkeypatch.setattr(avatar_validator, "MAX_AVATAR_SIZE", 10)  # 10 bytes para forzar el limite
    files = {"file": ("avatar.png", _fake_image_bytes("PNG"), "image/png")}
    response = await client.patch(URL_AVATAR, files=files, headers=_headers(user_id))
    assert response.status_code == 422


async def test_upload_avatar_rejects_empty_file(client, user_id):
    """CA 2 + CA 3: archivo vacio."""
    files = {"file": ("avatar.png", b"", "image/png")}
    response = await client.patch(URL_AVATAR, files=files, headers=_headers(user_id))
    assert response.status_code == 422


# Conflictos de negocio (username duplicado) — parte de CA 3

async def test_username_already_taken_returns_409(client, db_session, user_id):
    other_name = _unique("taken")
    await _create_user(db_session, other_name)

    response = await client.patch(URL_PROFILE, json={"username": other_name}, headers=_headers(user_id))
    assert response.status_code == 409


async def test_username_race_condition_returns_409(client, db_session, user_id, monkeypatch):
    from app.repositories.profile_repository import ProfileRepository

    other_name = _unique("race")
    await _create_user(db_session, other_name)

    async def not_found(self, username):
        return None

    monkeypatch.setattr(ProfileRepository, "get_by_username", not_found)

    response = await client.patch(URL_PROFILE, json={"username": other_name}, headers=_headers(user_id))
    assert response.status_code == 409


# Autenticacion / recursos inexistentes — transversal a CA 1 y CA 2

async def test_missing_user_header_returns_401(client):
    response = await client.patch(URL_PROFILE, json={"bio": "hola"})
    assert response.status_code == 401


async def test_unknown_user_returns_404(client):
    response = await client.patch(URL_PROFILE, json={"bio": "hola"}, headers=_headers(str(uuid.uuid4())))
    assert response.status_code == 404


async def test_upload_avatar_missing_user_header_returns_401(client):
    files = {"file": ("avatar.png", _fake_image_bytes("PNG"), "image/png")}
    response = await client.patch(URL_AVATAR, files=files)
    assert response.status_code == 401


async def test_upload_avatar_unknown_user_returns_404(client):
    files = {"file": ("avatar.png", _fake_image_bytes("PNG"), "image/png")}
    response = await client.patch(URL_AVATAR, files=files, headers=_headers(str(uuid.uuid4())))
    assert response.status_code == 404