from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class UserBlock(Base):
    __tablename__ = "user_blocks"
    __table_args__ = (
        CheckConstraint("blocker_id <> blocked_id", name="not_self"),
        Index("ix_user_blocks_blocked_id", "blocked_id"),
    )

    blocker_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    blocked_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
