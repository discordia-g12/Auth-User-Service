import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_my_profile_success(client: AsyncClient, auth_headers: dict[str, str]):
    # Provision profile first
    payload = {
        "username": "profile_explorer",
        "bio": "Exploring the virtual universe.",
        "avatar_url": "https://cdn.discordia.app/avatars/explorer.png",
    }
    create_res = await client.post("/api/v1/users/me", json=payload, headers=auth_headers)
    assert create_res.status_code == 201

    # Retrieve profile
    res = await client.get("/api/v1/users/me", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["user_id"] == auth_headers["X-User-Id"]
    assert data["username"] == "profile_explorer"
    assert data["bio"] == "Exploring the virtual universe."
    assert data["avatar_url"] == "https://cdn.discordia.app/avatars/explorer.png"
    assert data["activity_status"] == "offline"


@pytest.mark.asyncio
async def test_get_my_profile_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    # Request profile for user that has not registered yet
    res = await client.get("/api/v1/users/me", headers=auth_headers)
    assert res.status_code == 404
    data = res.json()
    assert data["status"] == 404
    assert "has not been initialized" in data["detail"].lower()


@pytest.mark.asyncio
async def test_get_my_profile_unauthenticated(client: AsyncClient):
    # Request profile without X-User-Id header
    res = await client.get("/api/v1/users/me")
    assert res.status_code == 401
    data = res.json()
    assert data["status"] == 401
    assert "Unauthenticated" in data["detail"]
