from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SuspendUserRequest(BaseModel):
    """Staff suspends an account (backoffice, "Suspender usuario a nivel plataforma")."""

    user: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description='Who to suspend: email, "@username" or user id',
        examples=["@cyber_samurai", "someone@example.com"],
    )
    reason: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Why: stored with the suspension and sent in the user.suspended event (audit)",
    )


class PlatformUserSummary(BaseModel):
    """An account as the backoffice shows it, with its suspension state."""

    user_id: str
    username: str | None = None
    display_name: str | None = None
    email: str
    is_suspended: bool
    suspended_at: datetime | None = None
    suspended_by: str | None = None
    suspension_reason: str | None = None
    created_at: datetime


AccountStateFilter = Literal["all", "active", "suspended"]


class PlatformUserPage(BaseModel):
    """A page of the staff user directory ("Ver listado de usuarios con filtros")."""

    items: list[PlatformUserSummary]
    total: int = Field(..., description="Accounts matching the filters, across all pages")
    page: int
    page_size: int
