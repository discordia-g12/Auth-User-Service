from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedIdentity, get_authenticated_identity
from app.db.session import get_db
from app.exceptions import BadRequestError, EmailNotVerifiedError
from app.schemas.problem import ProblemDetails
from app.schemas.user import BulkUserRequest, CreateUserProfileRequest, UserProfileResponse
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["Users"])
user_service = UserService()


@router.post(
    "/me",
    status_code=status.HTTP_201_CREATED,
    response_model=UserProfileResponse,
    summary="Provision initial user profile",
    description="Registers the business user record and profile for the authenticated identity verified by Gateway.",
    responses={
        status.HTTP_201_CREATED: {
            "model": UserProfileResponse,
            "description": "Profile successfully created",
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ProblemDetails,
            "description": "Missing required email header",
        },
        status.HTTP_401_UNAUTHORIZED: {
            "model": ProblemDetails,
            "description": "Unauthenticated identity",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ProblemDetails,
            "description": "Email address not verified in the identity provider",
        },
        status.HTTP_409_CONFLICT: {
            "model": ProblemDetails,
            "description": "User already registered or username in use",
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "model": ProblemDetails,
            "description": "Payload boundary validation error",
        },
    },
)
async def register_user_profile(
    payload: CreateUserProfileRequest,
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserProfileResponse:
    """Provisions profile for authenticated user on Discordia platform."""
    if not identity.email:
        raise BadRequestError("User email is required to register an account in Discordia.")

    # Second barrier. The primary one is the Auth0 Post Login Action
    if not identity.email_verified:
        raise EmailNotVerifiedError()

    return await user_service.register_user_profile(
        session=db,
        user_id=identity.user_id,
        email=identity.email,
        request=payload,
    )


@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    response_model=UserProfileResponse,
    summary="Get own profile for authenticated user",
    description="Returns current profile and activity status for the verified JWT user.",
    responses={
        status.HTTP_200_OK: {
            "model": UserProfileResponse,
            "description": "Profile successfully retrieved",
        },
        status.HTTP_401_UNAUTHORIZED: {
            "model": ProblemDetails,
            "description": "Unauthenticated identity",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ProblemDetails,
            "description": "Profile not yet initialized",
        },
    },
)
async def get_my_profile(
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserProfileResponse:
    """Retrieves profile of the currently authenticated user."""
    return await user_service.get_my_profile(
        session=db,
        user_id=identity.user_id,
    )


@router.post(
    "/bulk",
    status_code=status.HTTP_200_OK,
    response_model=list[UserProfileResponse],
    summary="Fetch multiple user profiles",
    description="Returns public profile data for a given list of user IDs. Only retrieves initialized profiles.",
)
async def get_users_bulk(
    payload: BulkUserRequest,
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[UserProfileResponse]:
    """Retrieves profiles for multiple users."""
    return await user_service.get_users_bulk(
        session=db,
        user_ids=payload.user_ids,
    )
