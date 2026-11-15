import pytest

from app.api.deps import AuthenticatedIdentity, get_authenticated_identity, require_staff
from app.exceptions import StaffOnlyError, UnauthorizedError


@pytest.mark.asyncio
async def test_identity_with_verified_email():
    identity = await get_authenticated_identity(
        x_user_id="auth0|abc", x_user_email="a@discordia.com", x_user_email_verified="true"
    )
    assert identity == AuthenticatedIdentity(user_id="auth0|abc", email="a@discordia.com", email_verified=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [None, "", "false", "False", "0", "1", "yes", "truee"])
async def test_identity_email_verified_fails_closed(raw: str | None):
    identity = await get_authenticated_identity(x_user_id="auth0|abc", x_user_email="a@x.co", x_user_email_verified=raw)
    assert identity.email_verified is False


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["true", "TRUE", " True "])
async def test_identity_email_verified_accepts_true_literal(raw: str):
    identity = await get_authenticated_identity(x_user_id="auth0|abc", x_user_email="a@x.co", x_user_email_verified=raw)
    assert identity.email_verified is True


@pytest.mark.asyncio
@pytest.mark.parametrize(("raw", "expected"), [(None, "user"), ("", "user"), ("  ", "user"), (" staff ", "staff")])
async def test_identity_role_defaults_to_user(raw: str | None, expected: str):
    identity = await get_authenticated_identity(
        x_user_id="auth0|abc", x_user_email=None, x_user_email_verified=None, x_user_role=raw
    )
    assert identity.role == expected


@pytest.mark.asyncio
async def test_require_staff_accepts_only_staff():
    staff = AuthenticatedIdentity(user_id="auth0|s", role="staff")
    assert await require_staff(staff) is staff
    for role in ("user", "Staff", "admin"):
        with pytest.raises(StaffOnlyError):
            await require_staff(AuthenticatedIdentity(user_id="auth0|u", role=role))


@pytest.mark.asyncio
async def test_identity_missing_user_id_raises():
    with pytest.raises(UnauthorizedError):
        await get_authenticated_identity(x_user_id=None, x_user_email="a@x.com", x_user_email_verified="true")
