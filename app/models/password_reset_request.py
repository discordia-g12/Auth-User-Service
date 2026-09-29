import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PasswordResetRequest(Base):
    """One password reset request.

    Stores the SHA-256 of the normalized email instead of the email itself. Rows older than the
    rate-limit window are purged on every new request.
    """

    __tablename__ = "password_reset_requests"
    __table_args__ = (Index("ix_password_reset_requests_email_hash_requested_at", "email_hash", "requested_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
