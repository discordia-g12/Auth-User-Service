from collections.abc import AsyncGenerator

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import OperationalError

from app.db.session import get_db
from app.main import app as fastapi_app


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient):
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "Auth & User Service"
    assert data["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_liveness_probe(client: AsyncClient):
    response = await client.get("/livez")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


@pytest.mark.asyncio
async def test_readiness_probe(client: AsyncClient):
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


LEAKY_DRIVER_MESSAGE = 'password authentication failed for user "admin" on host 10.0.0.5, database "auth_db"'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        OperationalError("SELECT 1", {}, Exception(LEAKY_DRIVER_MESSAGE)),
        ConnectionRefusedError(LEAKY_DRIVER_MESSAGE),
    ],
)
async def test_readiness_probe_db_down_does_not_leak_details(client: AsyncClient, error: Exception):
    class BrokenSession:
        async def execute(self, *args, **kwargs):
            raise error

    async def broken_db() -> AsyncGenerator[BrokenSession, None]:
        yield BrokenSession()

    # The client fixture installs its own override; replace it only for this test.
    fastapi_app.dependency_overrides[get_db] = broken_db

    response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    for fragment in ("admin", "10.0.0.5", "auth_db", "password"):
        assert fragment not in response.text
