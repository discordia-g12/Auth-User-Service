import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

USERNAME_MIN = 3
USERNAME_MAX = 32
BIO_MAX = 190
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.]+$")


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str | None = Field(default=None)
    display_name: str | None = Field(default=None, max_length=64)
    bio: str | None = Field(default=None, max_length=BIO_MAX)
    custom_status: str | None = Field(default=None, max_length=64)
    avatar_url: str | None = Field(default=None)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) < USERNAME_MIN or len(value) > USERNAME_MAX:
            raise ValueError(f"username must be between {USERNAME_MIN} and {USERNAME_MAX} characters")
        if not USERNAME_PATTERN.match(value):
            raise ValueError("username can only contain letters, numbers, '_' and '.'")
        return value

    @field_validator("bio")
    @classmethod
    def normalize_bio(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_fields(self) -> "ProfileUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be sent to edit")
        if "username" in self.model_fields_set and self.username is None:
            raise ValueError("username cannot be null")
        return self


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    custom_status: str | None = None
