from datetime import datetime

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.friend_request import FriendRequest, FriendRequestStatus
from app.models.friendship import Friendship, ordered_pair
from app.models.user import User
from app.models.user_block import UserBlock


class SocialRepository:
    """Friend requests, friendships and blocks. Every id here is canonical: resolve aliases before calling."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def lock_pair(self, user_a: str, user_b: str) -> None:
        """Serializes every change between two users until the transaction ends.

        The partial unique index does not cover crossed requests (A→B and B→A are different rows), nor a
        block racing an accept. Locks the two user rows, always in the same order to avoid deadlocks. NO KEY
        UPDATE does not block the foreign keys that point to them. SQLite ignores it.
        """
        stmt = select(User.id).where(User.id.in_((user_a, user_b))).order_by(User.id).with_for_update(key_share=True)
        await self.db.execute(stmt)

    async def get_request(self, request_id: str) -> FriendRequest | None:
        return await self.db.get(FriendRequest, request_id)

    async def get_pending_request(self, requester_id: str, addressee_id: str) -> FriendRequest | None:
        stmt = select(FriendRequest).where(
            FriendRequest.requester_id == requester_id,
            FriendRequest.addressee_id == addressee_id,
            FriendRequest.status == FriendRequestStatus.PENDING.value,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_pending_requests(self, user_id: str) -> list[FriendRequest]:
        """Pending requests the user sent or received, most recent first."""
        stmt = (
            select(FriendRequest)
            .where(
                or_(FriendRequest.requester_id == user_id, FriendRequest.addressee_id == user_id),
                FriendRequest.status == FriendRequestStatus.PENDING.value,
            )
            .order_by(FriendRequest.created_at.desc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    def add_request(
        self,
        requester_id: str,
        addressee_id: str,
        message: str | None,
        status: FriendRequestStatus,
        created_at: datetime,
    ) -> FriendRequest:
        request = FriendRequest(
            requester_id=requester_id,
            addressee_id=addressee_id,
            message=message,
            status=status.value,
            created_at=created_at,
            responded_at=None if status is FriendRequestStatus.PENDING else created_at,
        )
        self.db.add(request)
        return request

    async def resolve_pending_between(
        self, user_a: str, user_b: str, status: FriendRequestStatus, responded_at: datetime
    ) -> None:
        stmt = (
            update(FriendRequest)
            .where(
                FriendRequest.requester_id.in_((user_a, user_b)),
                FriendRequest.addressee_id.in_((user_a, user_b)),
                FriendRequest.status == FriendRequestStatus.PENDING.value,
            )
            .values(status=status.value, responded_at=responded_at)
        )
        await self.db.execute(stmt)

    async def are_friends(self, user_a: str, user_b: str) -> bool:
        low, high = ordered_pair(user_a, user_b)
        stmt = select(Friendship.user_low_id).where(Friendship.user_low_id == low, Friendship.user_high_id == high)
        return (await self.db.execute(stmt)).first() is not None

    def add_friendship(self, user_a: str, user_b: str, created_at: datetime) -> None:
        low, high = ordered_pair(user_a, user_b)
        self.db.add(Friendship(user_low_id=low, user_high_id=high, created_at=created_at))

    async def remove_friendship(self, user_a: str, user_b: str) -> None:
        low, high = ordered_pair(user_a, user_b)
        await self.db.execute(
            delete(Friendship).where(Friendship.user_low_id == low, Friendship.user_high_id == high)
        )

    async def friend_ids(self, user_id: str) -> set[str]:
        stmt = select(Friendship.user_low_id, Friendship.user_high_id).where(
            or_(Friendship.user_low_id == user_id, Friendship.user_high_id == user_id)
        )
        rows = (await self.db.execute(stmt)).all()
        return {high if low == user_id else low for low, high in rows}

    async def is_blocked(self, blocker_id: str, blocked_id: str) -> bool:
        stmt = select(UserBlock.blocker_id).where(
            UserBlock.blocker_id == blocker_id, UserBlock.blocked_id == blocked_id
        )
        return (await self.db.execute(stmt)).first() is not None

    def add_block(self, blocker_id: str, blocked_id: str, created_at: datetime) -> None:
        self.db.add(UserBlock(blocker_id=blocker_id, blocked_id=blocked_id, created_at=created_at))

    async def remove_block(self, blocker_id: str, blocked_id: str) -> None:
        await self.db.execute(
            delete(UserBlock).where(UserBlock.blocker_id == blocker_id, UserBlock.blocked_id == blocked_id)
        )

    async def blocked_ids(self, blocker_id: str) -> set[str]:
        stmt = select(UserBlock.blocked_id).where(UserBlock.blocker_id == blocker_id)
        return set((await self.db.execute(stmt)).scalars().all())
