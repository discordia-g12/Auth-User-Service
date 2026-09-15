import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import UserAlreadyExistsError, UsernameConflictError, UserProfileNotFoundError
from app.schemas.user import CreateUserProfileRequest
from app.services.user_service import UserService


@pytest.mark.asyncio
async def test_user_service_registration_and_retrieval(db_session: AsyncSession):
    service = UserService()
    req = CreateUserProfileRequest(username="service_tester", bio="Direct service test.")

    # 1. Register
    created = await service.register_user_profile(
        session=db_session,
        user_id="auth0|service-1",
        email="service1@discordia.com",
        request=req,
    )
    assert created.username == "service_tester"
    assert created.user_id == "auth0|service-1"

    # 2. Retrieve
    retrieved = await service.get_my_profile(session=db_session, user_id="auth0|service-1")
    assert retrieved.username == "service_tester"
    assert retrieved.user_id == "auth0|service-1"


@pytest.mark.asyncio
async def test_user_service_user_already_exists_error(db_session: AsyncSession):
    service = UserService()
    req1 = CreateUserProfileRequest(username="alpha_user")
    req2 = CreateUserProfileRequest(username="beta_user")

    await service.register_user_profile(
        session=db_session,
        user_id="auth0|duplicate-id",
        email="dup@discordia.com",
        request=req1,
    )

    with pytest.raises(UserAlreadyExistsError):
        await service.register_user_profile(
            session=db_session,
            user_id="auth0|duplicate-id",
            email="dup2@discordia.com",
            request=req2,
        )


@pytest.mark.asyncio
async def test_user_service_username_conflict_error(db_session: AsyncSession):
    service = UserService()
    req = CreateUserProfileRequest(username="shared_username")

    await service.register_user_profile(
        session=db_session,
        user_id="auth0|first-user",
        email="user1@discordia.com",
        request=req,
    )

    with pytest.raises(UsernameConflictError):
        await service.register_user_profile(
            session=db_session,
            user_id="auth0|second-user",
            email="user2@discordia.com",
            request=req,
        )


@pytest.mark.asyncio
async def test_user_service_profile_not_found_error(db_session: AsyncSession):
    service = UserService()
    with pytest.raises(UserProfileNotFoundError):
        await service.get_my_profile(session=db_session, user_id="auth0|non-existent")

