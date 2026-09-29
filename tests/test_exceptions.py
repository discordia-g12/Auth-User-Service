import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_app_exception_rfc7807_format(client: AsyncClient, auth_headers: dict[str, str]):
    # Request a path with malformed payload to trigger validation_exception_handler
    response = await client.post("/api/v1/users/me", json={"username": ""}, headers=auth_headers)

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    data = response.json()
    assert data["type"] == "about:blank"
    assert data["title"] == "Validation Error"
    assert data["status"] == 422
    assert "invalid_params" in data
    assert any(p["name"] == "username" for p in data["invalid_params"])


@pytest.mark.asyncio
async def test_not_found_endpoint_rfc7807_format(client: AsyncClient):
    response = await client.get("/api/v1/non-existent-endpoint")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    data = response.json()
    assert data["type"] == "about:blank"
    assert data["status"] == 404
    assert data["instance"] == "/api/v1/non-existent-endpoint"


def test_problem_types_contract():
    """Guards the `type` URIs that web/mobile clients branch on. Changing one is a breaking API change."""
    from app.exceptions import AppException, EmailNotVerifiedError, ForbiddenError, UserAlreadyExistsError

    assert AppException("x").type == "about:blank"
    assert ForbiddenError().type == "about:blank"
    assert UserAlreadyExistsError().type == "about:blank"
    assert EmailNotVerifiedError().type == "https://discordia.app/problems/email-not-verified"
    assert EmailNotVerifiedError().status_code == 403
