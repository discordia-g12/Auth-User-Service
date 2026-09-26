from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.exceptions import ConflictError, UserAlreadyExistsError, UsernameConflictError, UserProfileNotFoundError
from app.repositories.user_repository import UserRepository
from app.schemas.user import CreateUserProfileRequest, UserProfileResponse
from app.services.validation import no_null_bytes

logger = get_logger(__name__)


class UserService:
    def __init__(self, user_repo: UserRepository | None = None):
        self.user_repo = user_repo or UserRepository()

    async def register_user_profile(
        self, session: AsyncSession, user_id: str, email: str, request: CreateUserProfileRequest
    ) -> UserProfileResponse:
        """Initializes business user record and profile for the authenticated identity."""
        no_null_bytes(request.username, "username")
        no_null_bytes(request.bio, "bio")
        no_null_bytes(request.avatar_url, "avatar_url")

        existing_user = await self.user_repo.get_user_by_id(session, user_id)
        if existing_user is not None:
            logger.warning("user_already_registered", user_id=user_id)
            raise UserAlreadyExistsError()

        existing_profile = await self.user_repo.get_profile_by_username(session, request.username)
        if existing_profile is not None:
            logger.warning("username_conflict", username=request.username)
            raise UsernameConflictError(request.username)

        try:
            user, profile = await self.user_repo.create_user_profile_and_outbox(
                session=session,
                user_id=user_id,
                username=request.username,
                email=email,
                bio=request.bio,
                avatar_url=request.avatar_url,
                outbox_payload={"user_id": user_id, "username": request.username, "email": email},
            )
            await session.commit()
            await session.refresh(user)
            await session.refresh(profile)

        except IntegrityError as exc:
            await session.rollback()
            logger.warning("database_integrity_conflict", user_id=user_id, error=str(exc))
            raise ConflictError("A database integrity conflict occurred while creating user profile.")

        logger.info("user_registered", user_id=user_id, username=profile.username)

        return UserProfileResponse(
            user_id=user.id,
            username=profile.username,
            avatar_url=profile.avatar_url,
            bio=profile.bio,
            activity_status=profile.activity_status,
            custom_status=profile.custom_status,
            created_at=user.created_at,
        )

    async def get_my_profile(self, session: AsyncSession, user_id: str) -> UserProfileResponse:
        """Retrieves profile of the currently authenticated user."""
        user = await self.user_repo.get_user_by_id(session, user_id)
        if user is None or user.profile is None:
            logger.warning("user_profile_not_found", user_id=user_id)
            raise UserProfileNotFoundError()

        profile = user.profile
        return UserProfileResponse(
            user_id=user.id,
            username=profile.username,
            avatar_url=profile.avatar_url,
            bio=profile.bio,
            activity_status=profile.activity_status,
            custom_status=profile.custom_status,
            created_at=user.created_at,
        )
