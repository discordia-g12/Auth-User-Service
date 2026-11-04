from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CreateUserProfileRequest(BaseModel):
    """Request payload for registering the initial profile of an authenticated user."""

    username: str = Field(
        ...,
        min_length=3,
        max_length=32,
        pattern=r"^[a-zA-Z0-9_.-]+$",
        description="Unique username on the Discordia platform",
        examples=["cyber_samurai"],
    )
    display_name: str | None = Field(
        default=None,
        max_length=64,
        description="Display name",
    )
    bio: str | None = Field(
        default=None,
        max_length=190,
        description="Short user biography",
        examples=["Open-source enthusiast and gamer."],
    )
    avatar_url: str | None = Field(
        default=None,
        max_length=500,
        description="Public URL for the user avatar image",
    )


class UserProfileResponse(BaseModel):
    """Response payload containing business user and profile data."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str = Field(..., description="Opaque external identity identifier")
    username: str = Field(..., description="Unique Discordia username")
    display_name: str | None = Field(default=None, description="Display name")
    avatar_url: str | None = Field(default=None, description="Public avatar URL")
    bio: str | None = Field(default=None, description="User biography")
    activity_status: str = Field(default="offline", description="Real-time activity status")
    custom_status: str | None = Field(default=None, description="Custom status message")
    created_at: datetime = Field(..., description="Creation timestamp in ISO 8601 format")


class BulkUserRequest(BaseModel):
    user_ids: list[str] = Field(..., max_length=100, description="List of user IDs to fetch")


class ResolveIdentityResponse(BaseModel):
    user_id: str = Field(..., description="Canonical user ID resolved for this identity")
    found: bool = Field(..., description="Whether an existing user record was found")

