import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


@pytest.mark.asyncio
async def test_user_default_values(db_session: AsyncSession):
    user = User(id="auth0|test-user", email="user@example.com")
    db_session.add(user)
    await db_session.flush()

    assert user.id == "auth0|test-user"
    assert user.email == "user@example.com"
    assert user.is_active is True
    assert user.is_suspended is False

    await db_session.rollback()
