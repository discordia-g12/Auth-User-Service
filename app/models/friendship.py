from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class Friendship(Base):
    __tablename__ = "friendships"
    __table_args__ = (
        CheckConstraint("user_low_id <> user_high_id", name="not_self"),
        Index("ix_friendships_user_high_id", "user_high_id"),
    )

    user_low_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    user_high_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def ordered_pair(user_a: str, user_b: str) -> tuple[str, str]:
    return (user_a, user_b) if user_a < user_b else (user_b, user_a)
