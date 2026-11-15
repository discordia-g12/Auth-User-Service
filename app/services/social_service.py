from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.exceptions import (
    AlreadyFriendsError,
    FriendRequestAlreadyPendingError,
    FriendRequestNotFoundError,
    NotFoundError,
    ProfileNotAvailableError,
    SelfRelationError,
)
from app.models.friend_request import FriendRequest, FriendRequestStatus
from app.models.user import User
from app.repositories.social_repository import SocialRepository
from app.repositories.user_repository import UserRepository
from app.schemas.internal import CanonicalUserResponse, RelationsResponse
from app.schemas.social import (
    FriendAccepted,
    FriendRequestCreate,
    FriendRequestResponse,
    FriendRequestsResponse,
    PublicProfile,
    Relationship,
)
from app.services.user_service import public_profile_view
from app.services.validation import no_null_bytes

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _is_visible(user: User | None) -> bool:
    return user is not None and user.profile is not None and not user.is_suspended


@dataclass(frozen=True)
class _ViewerRelations:
    """Everything `viewer` has with other users, loaded once to build a whole list of profiles."""

    friends: set[str]
    blocked: set[str]
    sent: dict[str, str]
    received: dict[str, str]

    def of(self, user_id: str) -> tuple[Relationship, str | None]:
        if user_id in self.blocked:
            return Relationship.BLOCKED, None
        if user_id in self.friends:
            return Relationship.FRIEND, None
        if user_id in self.sent:
            return Relationship.REQUEST_SENT, self.sent[user_id]
        if user_id in self.received:
            return Relationship.REQUEST_RECEIVED, self.received[user_id]
        return Relationship.NONE, None


class SocialService:
    """Friend requests, friendships and blocks (#36, #43 and part of #42).

    Every change between two users runs under `lock_pair`, and whatever depends on the current state is read
    after taking it. Users are canonical: `actor` already is, and any other id goes through
    `resolve_canonical_user`, because `friendships` and `user_blocks` only store canonical ids.
    """

    def __init__(
        self,
        db: AsyncSession,
        repo: SocialRepository | None = None,
        user_repo: UserRepository | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ):
        self.db = db
        self.repo = repo or SocialRepository(db)
        self.user_repo = user_repo or UserRepository()
        self.clock = clock

    async def _viewer_relations(self, viewer_id: str) -> _ViewerRelations:
        pending = await self.repo.list_pending_requests(viewer_id)
        return _ViewerRelations(
            friends=await self.repo.friend_ids(viewer_id),
            blocked=await self.repo.blocked_ids(viewer_id),
            sent={r.addressee_id: r.id for r in pending if r.requester_id == viewer_id},
            received={r.requester_id: r.id for r in pending if r.addressee_id == viewer_id},
        )

    @staticmethod
    def _to_profile(user: User, relations: _ViewerRelations) -> PublicProfile:
        relationship, request_id = relations.of(user.id)
        view = public_profile_view(user, user.id)
        return PublicProfile(
            user_id=view.user_id,
            username=view.username,
            display_name=view.display_name,
            avatar_url=view.avatar_url,
            bio=view.bio,
            custom_status=view.custom_status,
            created_at=view.created_at,
            relationship=relationship,
            friend_request_id=request_id,
        )

    async def _profiles_by_ids(self, viewer_id: str, user_ids: set[str]) -> list[PublicProfile]:
        """Suspended accounts stay on the list with the public view of a suspended account (name only):
        the viewer still has to be able to unfriend or unblock them."""
        users = await self.user_repo.get_users_by_ids(self.db, list(user_ids))
        relations = await self._viewer_relations(viewer_id)
        profiles = [self._to_profile(user, relations) for user in users if user.profile is not None]
        return sorted(profiles, key=lambda profile: profile.username.lower())

    async def _profile(self, viewer_id: str, user: User) -> PublicProfile:
        return self._to_profile(user, await self._viewer_relations(viewer_id))

    async def get_profile(self, actor: User, user_id: str) -> PublicProfile:
        user = await self.user_repo.resolve_canonical_user(self.db, user_id)
        if not _is_visible(user):
            raise ProfileNotAvailableError()
        return await self._profile(actor.id, user)

    async def list_friends(self, actor: User) -> list[PublicProfile]:
        return await self._profiles_by_ids(actor.id, await self.repo.friend_ids(actor.id))

    async def remove_friend(self, actor: User, user_id: str) -> None:
        user = await self.user_repo.resolve_canonical_user(self.db, user_id)
        if user is None:
            return
        await self.repo.remove_friendship(actor.id, user.id)
        await self.db.commit()

    async def list_friend_requests(self, actor: User) -> FriendRequestsResponse:
        pending = await self.repo.list_pending_requests(actor.id)
        other_ids = {r.requester_id if r.addressee_id == actor.id else r.addressee_id for r in pending}
        users = await self.user_repo.get_users_by_ids(self.db, list(other_ids))
        visible = {user.id: user for user in users if _is_visible(user)}
        relations = await self._viewer_relations(actor.id)

        result = FriendRequestsResponse(incoming=[], outgoing=[])
        for request in pending:
            incoming = request.addressee_id == actor.id
            other = visible.get(request.requester_id if incoming else request.addressee_id)
            if other is not None:
                response = self._to_request_response(request, self._to_profile(other, relations))
                (result.incoming if incoming else result.outgoing).append(response)
        return result

    @staticmethod
    def _to_request_response(request: FriendRequest, user: PublicProfile) -> FriendRequestResponse:
        return FriendRequestResponse(id=request.id, user=user, message=request.message, created_at=request.created_at)

    async def _find_target(self, payload: FriendRequestCreate) -> tuple[User | None, bool]:
        """The user a request points to and whether it was looked up by email."""
        if payload.user_id is not None:
            return await self.user_repo.resolve_canonical_user(self.db, payload.user_id), False
        value = payload.target.strip()
        if "@" in value.removeprefix("@"):
            return await self.user_repo.find_user_by_email(self.db, value), True
        return await self.user_repo.find_user_by_username(self.db, value.removeprefix("@")), False

    async def send_friend_request(self, actor: User, payload: FriendRequestCreate) -> FriendRequestResponse | None:
        """Returns the request, or None when the answer must not reveal anything (202).

        By email the answer is always None, so it cannot be used to find out whether an account exists, is a
        friend or has a pending request. Against a block no row is created. The only exception is your own
        email (422), which reveals nothing.
        """
        no_null_bytes(payload.target, "target")
        no_null_bytes(payload.user_id, "user_id")
        no_null_bytes(payload.message, "message")

        target, by_email = await self._find_target(payload)
        if not _is_visible(target):
            if by_email:
                return None
            raise ProfileNotAvailableError()
        if target.id == actor.id:
            raise SelfRelationError()

        await self.repo.lock_pair(actor.id, target.id)

        if await self._is_blocked_either_way(actor.id, target.id):
            logger.info("friend_request_swallowed", actor=actor.id)
            return None
        if await self.repo.are_friends(actor.id, target.id):
            if by_email:
                return None
            raise AlreadyFriendsError()
        if await self.repo.get_pending_request(actor.id, target.id) is not None:
            if by_email:
                return None
            raise FriendRequestAlreadyPendingError()

        now = self.clock()
        if await self.repo.get_pending_request(target.id, actor.id) is not None:
            await self._befriend(actor.id, target.id, now)
            request = self.repo.add_request(actor.id, target.id, payload.message, FriendRequestStatus.ACCEPTED, now)
        else:
            request = self.repo.add_request(actor.id, target.id, payload.message, FriendRequestStatus.PENDING, now)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            # `lock_pair` already serializes this: the unique index is the last barrier
            await self.db.rollback()
            logger.warning("friend_request_integrity_conflict", error=str(exc))
            if by_email:
                return None
            raise FriendRequestAlreadyPendingError() from exc

        logger.info("friend_request_sent", request_id=request.id, status=request.status)
        if by_email:
            return None
        return self._to_request_response(request, await self._profile(actor.id, target))

    async def _is_blocked_either_way(self, user_a: str, user_b: str) -> bool:
        return await self.repo.is_blocked(user_a, user_b) or await self.repo.is_blocked(user_b, user_a)

    async def _befriend(self, user_a: str, user_b: str, now: datetime) -> None:
        await self.repo.resolve_pending_between(user_a, user_b, FriendRequestStatus.ACCEPTED, now)
        if not await self.repo.are_friends(user_a, user_b):
            self.repo.add_friendship(user_a, user_b, now)

    async def _lock_request(self, request_id: str, owner_id: str, owner_field: str) -> FriendRequest:
        """The request, re-read under the lock. 404 if it is not yours: its existence is not disclosed."""
        request = await self.repo.get_request(request_id)
        if request is None or getattr(request, owner_field) != owner_id:
            raise FriendRequestNotFoundError()
        await self.repo.lock_pair(request.requester_id, request.addressee_id)
        await self.db.refresh(request)
        return request

    async def accept_friend_request(self, actor: User, request_id: str) -> FriendAccepted:
        request = await self._lock_request(request_id, actor.id, "addressee_id")
        requester = await self.user_repo.get_user_by_id(self.db, request.requester_id)
        if not _is_visible(requester):
            raise FriendRequestNotFoundError()

        # La segunda aceptación (doble click, reintento) responde lo mismo que la primera
        already_accepted = request.status == FriendRequestStatus.ACCEPTED.value and await self.repo.are_friends(
            actor.id, requester.id
        )
        if not already_accepted:
            if request.status != FriendRequestStatus.PENDING.value:
                raise FriendRequestNotFoundError()
            await self._befriend(actor.id, requester.id, self.clock())
            await self.db.commit()
            logger.info("friend_request_accepted", request_id=request_id)
        return FriendAccepted(friend=await self._profile(actor.id, requester))

    async def _resolve_pending(self, request: FriendRequest, status: FriendRequestStatus) -> None:
        if request.status != FriendRequestStatus.PENDING.value:
            raise FriendRequestNotFoundError()
        request.status = status.value
        request.responded_at = self.clock()
        await self.db.commit()
        logger.info("friend_request_resolved", request_id=request.id, status=status.value)

    async def decline_friend_request(self, actor: User, request_id: str) -> None:
        request = await self._lock_request(request_id, actor.id, "addressee_id")
        await self._resolve_pending(request, FriendRequestStatus.DECLINED)

    async def cancel_friend_request(self, actor: User, request_id: str) -> None:
        request = await self._lock_request(request_id, actor.id, "requester_id")
        await self._resolve_pending(request, FriendRequestStatus.CANCELED)

    async def list_blocks(self, actor: User) -> list[PublicProfile]:
        return await self._profiles_by_ids(actor.id, await self.repo.blocked_ids(actor.id))

    async def block(self, actor: User, user_id: str) -> None:
        """Blocks and, in the same transaction, drops the friendship and the pending requests of both sides.
        History in Chat stays: there, the block only stops new messages."""
        user = await self.user_repo.resolve_canonical_user(self.db, user_id)
        if user is None:
            raise ProfileNotAvailableError()
        if user.id == actor.id:
            raise SelfRelationError()

        await self.repo.lock_pair(actor.id, user.id)
        if await self.repo.is_blocked(actor.id, user.id):
            return
        now = self.clock()
        self.repo.add_block(actor.id, user.id, now)
        await self.repo.remove_friendship(actor.id, user.id)
        await self.repo.resolve_pending_between(actor.id, user.id, FriendRequestStatus.CANCELED, now)
        await self.db.commit()
        logger.info("user_blocked", actor=actor.id)

    async def unblock(self, actor: User, user_id: str) -> None:
        """Only undoes the actor's own block. If the other one also blocked the actor, that one stays."""
        user = await self.user_repo.resolve_canonical_user(self.db, user_id)
        if user is None:
            return
        await self.repo.remove_block(actor.id, user.id)
        await self.db.commit()

    async def get_canonical(self, user_id: str) -> CanonicalUserResponse:
        user = await self.user_repo.resolve_canonical_user(self.db, user_id)
        if user is None:
            raise NotFoundError("User not found.")
        return CanonicalUserResponse(user_id=user.id, suspended=user.is_suspended)

    async def get_relations(self, actor_id: str, other_id: str) -> RelationsResponse:
        actor = await self.user_repo.resolve_canonical_user(self.db, actor_id)
        other = await self.user_repo.resolve_canonical_user(self.db, other_id)
        if actor is None or other is None:
            return RelationsResponse(
                exists=False, suspended=False, friends=False, blocked_by_actor=False, blocked_by_other=False
            )
        return RelationsResponse(
            exists=True,
            suspended=other.is_suspended,
            friends=await self.repo.are_friends(actor.id, other.id),
            blocked_by_actor=await self.repo.is_blocked(actor.id, other.id),
            blocked_by_other=await self.repo.is_blocked(other.id, actor.id),
        )
