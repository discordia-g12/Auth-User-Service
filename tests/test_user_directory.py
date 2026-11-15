from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_profile import UserProfile

URL = "/api/v1/admin/users"
STAFF_HEADERS = {"X-User-Id": "auth0|staff-1", "X-User-Role": "staff"}
BASE = datetime(2026, 1, 1, tzinfo=UTC)


async def _seed(db: AsyncSession) -> None:
    """Cuatro cuentas, de la más vieja a la más nueva. Una sin perfil (todavía no eligió usuario)."""
    rows = [
        ("auth0|1", "sofi@mail.com", "sofi", "Sofía Ríos", False),
        ("auth0|2", "tomas@mail.com", "tomasv", "Tomás Vera", True),
        ("auth0|3", "LUCIA@Mail.com", "lu_paz", "Lucía Paz", False),
        ("auth0|4", "nuevo@mail.com", None, None, False),
    ]
    for i, (user_id, email, username, display_name, suspended) in enumerate(rows):
        db.add(
            User(
                id=user_id,
                email=email,
                is_active=True,
                is_suspended=suspended,
                suspended_at=BASE if suspended else None,
                created_at=BASE + timedelta(days=i),
            )
        )
        if username:
            db.add(UserProfile(user_id=user_id, username=username, display_name=display_name))
    await db.commit()


def _ids(response) -> list[str]:
    return [u["user_id"] for u in response.json()["items"]]


@pytest.mark.asyncio
async def test_lists_every_account_newest_first(client: AsyncClient, db_session: AsyncSession):
    await _seed(db_session)

    response = await client.get(URL, headers=STAFF_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    assert body["page"] == 1
    assert _ids(response) == ["auth0|4", "auth0|3", "auth0|2", "auth0|1"]
    assert body["items"][0]["username"] is None  # sin perfil: el backoffice muestra el email


# CA 1: búsqueda por email o nombre


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("tomas@mail.com", ["auth0|2"]),  # email completo
        ("lucia@", ["auth0|3"]),  # parte del email, sin distinguir mayúsculas
        ("@tomasv", ["auth0|2"]),  # @usuario
        ("tom", ["auth0|2"]),  # parte del usuario
        ("ríos", ["auth0|1"]),  # nombre visible
        ("PAZ", ["auth0|3"]),
        ("mail.com", ["auth0|4", "auth0|3", "auth0|2", "auth0|1"]),
        ("nadie", []),
    ],
)
async def test_search_by_email_username_or_name(client: AsyncClient, db_session: AsyncSession, q, expected):
    await _seed(db_session)

    response = await client.get(URL, params={"q": q}, headers=STAFF_HEADERS)

    assert response.status_code == 200
    assert _ids(response) == expected
    assert response.json()["total"] == len(expected)


@pytest.mark.asyncio
async def test_like_wildcards_are_searched_literally(client: AsyncClient, db_session: AsyncSession):
    await _seed(db_session)

    # "_" es comodín de LIKE: sin escaparlo, "u_p" encontraría también "lupaz" o similares
    assert _ids(await client.get(URL, params={"q": "u_p"}, headers=STAFF_HEADERS)) == ["auth0|3"]
    assert _ids(await client.get(URL, params={"q": "%"}, headers=STAFF_HEADERS)) == []


# CA 2: filtro por estado


@pytest.mark.asyncio
async def test_filter_by_state(client: AsyncClient, db_session: AsyncSession):
    await _seed(db_session)

    suspended = await client.get(URL, params={"state": "suspended"}, headers=STAFF_HEADERS)
    active = await client.get(URL, params={"state": "active"}, headers=STAFF_HEADERS)

    assert _ids(suspended) == ["auth0|2"]
    assert all(u["is_suspended"] for u in suspended.json()["items"])
    assert _ids(active) == ["auth0|4", "auth0|3", "auth0|1"]


@pytest.mark.asyncio
async def test_search_and_state_combine(client: AsyncClient, db_session: AsyncSession):
    await _seed(db_session)

    response = await client.get(URL, params={"q": "tom", "state": "active"}, headers=STAFF_HEADERS)

    assert _ids(response) == []


@pytest.mark.asyncio
async def test_pagination(client: AsyncClient, db_session: AsyncSession):
    await _seed(db_session)

    first = await client.get(URL, params={"page": 1, "page_size": 3}, headers=STAFF_HEADERS)
    second = await client.get(URL, params={"page": 2, "page_size": 3}, headers=STAFF_HEADERS)

    assert _ids(first) == ["auth0|4", "auth0|3", "auth0|2"]
    assert _ids(second) == ["auth0|1"]
    assert second.json()["total"] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{"state": "deleted"}, {"page": 0}, {"page_size": 101}, {"q": "x" * 101}])
async def test_invalid_filters_are_422(client: AsyncClient, params):
    response = await client.get(URL, params=params, headers=STAFF_HEADERS)

    assert response.status_code == 422


# Solo staff


@pytest.mark.asyncio
async def test_non_staff_cannot_list(client: AsyncClient, db_session: AsyncSession):
    await _seed(db_session)

    response = await client.get(URL, headers={"X-User-Id": "auth0|1", "X-User-Role": "user"})

    assert response.status_code == 403
    assert response.json()["type"].endswith("/staff-only")


@pytest.mark.asyncio
async def test_listing_requires_identity(client: AsyncClient):
    response = await client.get(URL)

    assert response.status_code == 401
