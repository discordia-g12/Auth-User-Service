from pydantic import BaseModel, EmailStr, Field

GENERIC_RESET_MESSAGE = (
    "If the email is registered, you will receive a link to reset your password. The link expires in 1 hour."
)


class PasswordResetRequestBody(BaseModel):
    email: EmailStr = Field(..., max_length=254, description="Email of the account to recover")


class PasswordResetAcceptedResponse(BaseModel):
    detail: str = Field(default=GENERIC_RESET_MESSAGE)
