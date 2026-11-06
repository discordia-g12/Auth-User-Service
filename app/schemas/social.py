from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

FRIEND_REQUEST_MESSAGE_MAX = 190


class Relationship(StrEnum):
    """How the viewer relates to a user. Never says whether that user blocked the viewer: that case is `none`."""

    NONE = "none"
    FRIEND = "friend"
    REQUEST_SENT = "request_sent"
    REQUEST_RECEIVED = "request_received"
    BLOCKED = "blocked"


class PublicProfile(BaseModel):
    """What another user sees. Never carries the email nor anything about direct messages."""

    user_id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    custom_status: str | None = None
    created_at: datetime
    relationship: Relationship
    friend_request_id: str | None = None


class FriendRequestCreate(BaseModel):
    """Send a friend request by username or email (`target`) or from a profile (`user_id`)."""

    target: str | None = Field(default=None, min_length=1, max_length=255, description="Username or email")
    user_id: str | None = Field(default=None, min_length=1, max_length=255)
    message: str | None = Field(default=None, max_length=FRIEND_REQUEST_MESSAGE_MAX)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @model_validator(mode="after")
    def exactly_one_target(self) -> "FriendRequestCreate":
        if (self.target is None) == (self.user_id is None):
            raise ValueError("Send either target or user_id")
        return self


class FriendRequestResponse(BaseModel):
    id: str
    user: PublicProfile
    message: str | None = None
    created_at: datetime


class FriendRequestSent(BaseModel):
    """Answer that confirms nothing about the other account."""

    status: Literal["sent"] = "sent"


class FriendRequestsResponse(BaseModel):
    incoming: list[FriendRequestResponse]
    outgoing: list[FriendRequestResponse]


class FriendAccepted(BaseModel):
    friend: PublicProfile
