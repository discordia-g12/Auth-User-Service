from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user_profile import UserProfile
    from app.models.user_two_factor import UserTwoFactor


class User(Base):
    """User domain entity representing authenticated platform identity in Discordia."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    # Suspensión a nivel plataforma (ADR-002): cuándo, quién del staff y por qué. Vacíos si no está suspendida
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    suspended_by: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    suspension_reason: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    profile: Mapped["UserProfile"] = relationship(
        "UserProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    two_factor: Mapped["UserTwoFactor | None"] = relationship(
        "UserTwoFactor",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
