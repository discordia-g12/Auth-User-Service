from dataclasses import dataclass

from fastapi import Header

from app.exceptions import BadRequestError, UnauthorizedError


@dataclass(frozen=True)
class AuthenticatedIdentity:
    """Encapsulates verified identity provided by Gateway, abstracting HTTP transport details."""

    user_id: str
    email: str


async def get_authenticated_identity(x_user_id: str | None = Header(default=None, alias="X-User-Id"), x_user_email: str | None = Header(default=None, alias="X-User-Email")) -> AuthenticatedIdentity:
    """Extracts and validates identity headers injected by Kong Gateway."""
    if not x_user_id:
        raise UnauthorizedError("Unauthenticated user identity. Gateway token verification is required.")

    if not x_user_email:
        raise BadRequestError("User email is required to register an account in Discordia.")

    return AuthenticatedIdentity(user_id=x_user_id, email=x_user_email)
