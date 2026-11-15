import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base

PENDING_ONLY = text("status = 'pending'")


class FriendRequestStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELED = "canceled"


class FriendRequest(Base):
    __tablename__ = "friend_requests"
    __table_args__ = (
        CheckConstraint("requester_id <> addressee_id", name="not_self"),
        CheckConstraint("status IN ('pending', 'accepted', 'declined', 'canceled')", name="status_valid"),
        Index(
            "uq_friend_requests_pending_pair",
            "requester_id",
            "addressee_id",
            unique=True,
            postgresql_where=PENDING_ONLY,
            sqlite_where=PENDING_ONLY,
        ),
        Index("ix_friend_requests_addressee_id_status", "addressee_id", "status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    requester_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    addressee_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    message: Mapped[str | None] = mapped_column(String(190), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=FriendRequestStatus.PENDING.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
