from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.exceptions import StaffOnlyError, UnauthorizedError
from app.models.user import User

PLATFORM_STAFF_ROLE = "staff"


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
    # Platform role (claim https://discordia.app/role, propagated by Kong as X-User-Role)
    role: str = "user"


def _parse_bool_header(value: str | None) -> bool:
    """Only the exact literal 'true' (case-insensitive) counts as verified; anything else fails closed."""
    return value is not None and value.strip().lower() == "true"


async def get_authenticated_identity(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_user_email: str | None = Header(default=None, alias="X-User-Email"),
    x_user_email_verified: str | None = Header(default=None, alias="X-User-Email-Verified"),
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
) -> AuthenticatedIdentity:
    """Extracts and validates identity headers injected by Kong Gateway."""
    if not x_user_id:
        raise UnauthorizedError("Unauthenticated user identity. Gateway token verification is required.")

    return AuthenticatedIdentity(
        user_id=x_user_id,
        email=x_user_email,
        email_verified=_parse_bool_header(x_user_email_verified),
        role=(x_user_role or "user").strip(),
    )


async def require_staff(
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
) -> AuthenticatedIdentity:
    """Staff endpoints: 403 unless X-User-Role is exactly "staff" (fails closed on anything else).

    Kong already enforces validate("staff") on /api/v1/admin/*; this second check keeps a mistake in
    kong.yml from opening the backoffice (Gateway ADR-002, rule 2).
    """
    if identity.role != PLATFORM_STAFF_ROLE:
        raise StaffOnlyError()
    return identity


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
StaffIdentity = Annotated[AuthenticatedIdentity, Depends(require_staff)]
