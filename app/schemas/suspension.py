from datetime import datetime

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
