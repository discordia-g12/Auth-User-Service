from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.exceptions import (
    AccountSuspendedError,
    ConflictError,
    UserAlreadyExistsError,
    UsernameConflictError,
    UserProfileNotFoundError,
)
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import CreateUserProfileRequest, ResolveIdentityResponse, UserProfileResponse
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
        no_null_bytes(request.display_name, "display_name")
        no_null_bytes(request.bio, "bio")
        no_null_bytes(request.avatar_url, "avatar_url")

        existing_user = await self.user_repo.get_user_by_id(session, user_id)
        if existing_user is None:
            existing_user = await self.user_repo.get_user_by_email(session, email)

        if existing_user is not None and existing_user.profile is not None:
            if existing_user.id != user_id:
                await self.user_repo.ensure_identity_alias(session, user_id, existing_user.id)
            logger.info("user_already_registered_idempotent", user_id=user_id, resolved_user_id=existing_user.id)
            profile = existing_user.profile
            return UserProfileResponse(
                user_id=existing_user.id,
                username=profile.username,
                display_name=profile.display_name,
                avatar_url=profile.avatar_url,
                bio=profile.bio,
                activity_status=profile.activity_status,
                custom_status=profile.custom_status,
                created_at=existing_user.created_at,
            )
        elif existing_user is not None:
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
                display_name=request.display_name,
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
            display_name=profile.display_name,
            avatar_url=profile.avatar_url,
            bio=profile.bio,
            activity_status=profile.activity_status,
            custom_status=profile.custom_status,
            created_at=user.created_at,
        )

    async def get_my_profile(
        self,
        session: AsyncSession,
        user_id: str,
        email: str | None = None,
        email_verified: bool = False,
    ) -> UserProfileResponse:
        """Retrieves profile of the currently authenticated user, linking by verified email if needed."""
        user = await self.user_repo.get_user_by_id(session, user_id)
        if user is None and email and email_verified:
            user = await self.user_repo.get_user_by_email(session, email)
            if user is not None:
                await self.user_repo.ensure_identity_alias(session, user_id, user.id)
                logger.info("user_linked_by_verified_email", user_id=user_id, existing_user_id=user.id)
        if user is None or user.profile is None:
            logger.warning("user_profile_not_found", user_id=user_id)
            raise UserProfileNotFoundError()
        if user.is_suspended:
            # Kong ya rechaza sus tokens (lista de bloqueados): esto cubre una identidad nueva sin bloquear
            raise AccountSuspendedError()

        profile = user.profile
        return UserProfileResponse(
            user_id=user.id,
            username=profile.username,
            display_name=profile.display_name,
            avatar_url=profile.avatar_url,
            bio=profile.bio,
            activity_status=profile.activity_status,
            custom_status=profile.custom_status,
            created_at=user.created_at,
        )

    async def resolve_identity(
        self,
        session: AsyncSession,
        user_id: str,
        email: str | None = None,
        email_verified: bool = False,
    ) -> ResolveIdentityResponse:
        """Resolves an external IdP subject and verified email to the canonical user ID."""
        user = await self.user_repo.get_user_by_id(session, user_id)
        if user is not None:
            return ResolveIdentityResponse(user_id=user.id, found=True)
        if email and email_verified:
            user = await self.user_repo.get_user_by_email(session, email)
            if user is not None:
                await self.user_repo.ensure_identity_alias(session, user_id, user.id)
                logger.info("identity_resolved_by_verified_email", user_id=user_id, canonical_user_id=user.id)
                return ResolveIdentityResponse(user_id=user.id, found=True)
        return ResolveIdentityResponse(user_id=user_id, found=False)



    async def get_users_bulk(self, session: AsyncSession, user_ids: list[str]) -> list[UserProfileResponse]:
        """Retrieves profiles for a list of user IDs, including linked federated aliases."""
        users = await self.user_repo.get_users_by_ids(session, user_ids)
        found_ids = {user.id for user in users}
        responses = [_public_profile(user, user.id) for user in users if user.profile is not None]
        missing_ids = [uid for uid in user_ids if uid not in found_ids]
        if missing_ids:
            aliased = await self.user_repo.get_aliased_users_by_ids(session, missing_ids)
            responses.extend(
                _public_profile(user, alias_id) for alias_id, user in aliased.items() if user.profile is not None
            )
        return responses


def _public_profile(user: User, response_user_id: str) -> UserProfileResponse:
    """What other users see. A suspended account keeps its name (old messages still show who wrote them),
    but its profile is not available: no avatar, bio nor status (Suspender usuario, CA 1)."""
    profile = user.profile
    if user.is_suspended:
        return UserProfileResponse(
            user_id=response_user_id,
            username=profile.username,
            display_name=profile.display_name,
            activity_status="offline",
            created_at=user.created_at,
            is_suspended=True,
        )
    return UserProfileResponse(
        user_id=response_user_id,
        username=profile.username,
        display_name=profile.display_name,
        avatar_url=profile.avatar_url,
        bio=profile.bio,
        activity_status=profile.activity_status,
        custom_status=profile.custom_status,
        created_at=user.created_at,
    )
