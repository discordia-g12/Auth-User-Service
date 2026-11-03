from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.exceptions import UnauthorizedError
from app.models.user import User


@dataclass(frozen=True)
class AuthenticatedIdentity:
    """Encapsulates verified identity provided by Gateway, abstracting HTTP transport details.

    Trust model: these values come exclusively from headers that Kong writes after verifying
    the Auth0 JWT. Kong strips any client-supplied X-User-* header before validation, so a
    header present here was produced by the Gateway, never by the caller.
    """

    user_id: str
    email: str | None = None
    email_verified: bool = False


def _parse_bool_header(value: str | None) -> bool:
    """Only the exact literal 'true' (case-insensitive) counts as verified; anything else fails closed."""
    return value is not None and value.strip().lower() == "true"


async def get_authenticated_identity(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_user_email: str | None = Header(default=None, alias="X-User-Email"),
    x_user_email_verified: str | None = Header(default=None, alias="X-User-Email-Verified"),
) -> AuthenticatedIdentity:
    """Extracts and validates identity headers injected by Kong Gateway."""
    if not x_user_id:
        raise UnauthorizedError("Unauthenticated user identity. Gateway token verification is required.")

    return AuthenticatedIdentity(
        user_id=x_user_id,
        email=x_user_email,
        email_verified=_parse_bool_header(x_user_email_verified),
    )


async def get_current_user_id(
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> str:
    if identity.email and identity.email_verified:
        user = await db.get(User, identity.user_id)
        if user is None:
            result = await db.execute(select(User.id).where(User.email == identity.email))
            existing_id = result.scalar_one_or_none()
            if existing_id is not None:
                return existing_id
    return identity.user_id


DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentIdentity = Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)]
CurrentUserId = Annotated[str, Depends(get_current_user_id)]
