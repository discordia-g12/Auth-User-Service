from typing import Any

PROBLEM_TYPE_BASE = "https://discordia.app/problems"


class AppException(Exception):
    status_code: int = 500
    title: str = "Internal Server Error"
    type: str = "about:blank"

    def __init__(
        self,
        detail: str,
        status_code: int | None = None,
        title: str | None = None,
        invalid_params: list[dict[str, Any]] | None = None,
    ):
        super().__init__(detail)
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code
        if title is not None:
            self.title = title
        self.invalid_params = invalid_params


class BadRequestError(AppException):
    status_code = 400
    title = "Bad Request"


class UnauthorizedError(AppException):
    status_code = 401
    title = "Unauthorized"

    def __init__(self, detail: str = "Unauthenticated user identity. Gateway token verification is required."):
        super().__init__(detail)


class ForbiddenError(AppException):
    status_code = 403
    title = "Forbidden"

    def __init__(self, detail: str = "Forbidden access."):
        super().__init__(detail)


class NotFoundError(AppException):
    status_code = 404
    title = "Not Found"

    def __init__(self, detail: str = "Resource not found."):
        super().__init__(detail)


class ConflictError(AppException):
    status_code = 409
    title = "Conflict"

    def __init__(self, detail: str = "Resource conflict."):
        super().__init__(detail)


class UnprocessableEntityError(AppException):
    status_code = 422
    title = "Validation Error"


# Domain-Specific Exceptions
class UserAlreadyExistsError(ConflictError):
    def __init__(self, detail: str = "User already has a registered profile on the platform."):
        super().__init__(detail)


class UsernameConflictError(ConflictError):
    def __init__(self, username: str):
        super().__init__(f"Username '{username}' is already in use.")

class UsernameTakenError(ConflictError):
    def __init__(self, username: str | None = None):
        detail = f"Username '{username}' is already taken." if username else "Username is already taken."
        super().__init__(detail)

class EmailNotVerifiedError(ForbiddenError):
    type = f"{PROBLEM_TYPE_BASE}/email-not-verified"

    def __init__(
        self,
        detail: str = "Email address must be verified before registering in Discordia. Check your inbox.",
    ):
        super().__init__(detail)


class UserProfileNotFoundError(NotFoundError):
    def __init__(self, detail: str = "User profile has not been initialized."):
        super().__init__(detail)


class InvalidAvatarError(UnprocessableEntityError):
    def __init__(self, detail: str = "Invalid avatar file or format provided."):
        super().__init__(detail)


class AvatarUploadError(AppException):
    status_code = 500
    title = "Avatar Upload Failed"

    def __init__(self, detail: str = "Failed to process or upload avatar image."):
        super().__init__(detail)



__all__ = [
    "PROBLEM_TYPE_BASE",
    "AppException",
    "BadRequestError",
    "ConflictError",
    "EmailNotVerifiedError",
    "ForbiddenError",
    "NotFoundError",
    "UnauthorizedError",
    "UnprocessableEntityError",
    "UserAlreadyExistsError",
    "UserProfileNotFoundError",
    "UsernameConflictError",
]
