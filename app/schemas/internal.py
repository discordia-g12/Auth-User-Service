from pydantic import BaseModel, Field


class CanonicalUserResponse(BaseModel):
    user_id: str = Field(..., description="Canonical id: the alias already resolved")
    suspended: bool


class RelationsResponse(BaseModel):
    """How `actor` relates to `other`. If either one does not exist, everything comes back false."""

    exists: bool
    suspended: bool = Field(..., description="`other` is suspended")
    friends: bool
    blocked_by_actor: bool
    blocked_by_other: bool
