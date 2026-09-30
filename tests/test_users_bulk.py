import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_profile import UserProfile

URL_BULK = "/api/v1/users/bulk"

def _headers(user_id: str) -> dict[str, str]:
    return {"x-user-id": user_id, "x-user-email": "test@example.com", "x-email-verified": "true"}

@pytest.mark.asyncio
async def test_get_users_bulk_success(client: AsyncClient, db_session: AsyncSession):
    u1 = User(id="user_bulk_1", email="bulk1@test.com", is_active=True, is_suspended=False)
    p1 = UserProfile(user_id="user_bulk_1", username="bulk1", display_name="Bulk One", activity_status="online")
    
    u2 = User(id="user_bulk_2", email="bulk2@test.com", is_active=True, is_suspended=False)
    p2 = UserProfile(user_id="user_bulk_2", username="bulk2", display_name="Bulk Two", activity_status="offline")
    
    db_session.add_all([u1, p1, u2, p2])
    await db_session.commit()

    payload = {"user_ids": ["user_bulk_1", "user_bulk_2", "non_existent"]}
    response = await client.post(URL_BULK, json=payload, headers=_headers("user_bulk_1"))
    
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    
    usernames = [u["username"] for u in data]
    assert "bulk1" in usernames
    assert "bulk2" in usernames
    
    for u in data:
        if u["username"] == "bulk1":
            assert u["display_name"] == "Bulk One"

@pytest.mark.asyncio
async def test_get_users_bulk_empty_list(client: AsyncClient, db_session: AsyncSession):
    payload = {"user_ids": []}
    response = await client.post(URL_BULK, json=payload, headers=_headers("user_bulk_1"))
    assert response.status_code == 200
    assert response.json() == []

@pytest.mark.asyncio
async def test_get_users_bulk_unauthorized(client: AsyncClient):
    payload = {"user_ids": ["123"]}
    response = await client.post(URL_BULK, json=payload)
    assert response.status_code == 401

