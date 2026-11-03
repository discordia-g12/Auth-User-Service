from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    AuthenticatedIdentity,
    get_authenticated_identity,
    get_current_user_id,
)
from app.db.session import get_db
from app.exceptions import BadRequestError
from app.models.user import User
from app.schemas.two_factor import (
    TwoFactorActivateRequest,
    TwoFactorActivateResponse,
    TwoFactorDisableRequest,
    TwoFactorDisableResponse,
    TwoFactorRegenerateResponse,
    TwoFactorSetupResponse,
    TwoFactorStatusResponse,
    TwoFactorVerifyRequest,
    TwoFactorVerifyResponse,
)
from app.services.two_factor_service import TwoFactorService

router = APIRouter(prefix="/users/me/2fa", tags=["Two-Factor Authentication"])
two_factor_service = TwoFactorService()


@router.get(
    "/status",
    status_code=status.HTTP_200_OK,
    response_model=TwoFactorStatusResponse,
    summary="Get 2FA status for authenticated user",
)
async def get_two_factor_status(
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TwoFactorStatusResponse:
    return await two_factor_service.get_status(db, user_id)


@router.post(
    "/setup",
    status_code=status.HTTP_200_OK,
    response_model=TwoFactorSetupResponse,
    summary="Initialize 2FA setup with QR code and secret",
)
async def setup_two_factor(
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TwoFactorSetupResponse:
    email = identity.email
    if not email:
        user = await db.get(User, user_id)
        if user:
            email = user.email
    if not email:
        email = f"user_{user_id[:8]}@discordia.app"

    return await two_factor_service.setup_two_factor(db, user_id, email)


@router.post(
    "/activate",
    status_code=status.HTTP_200_OK,
    response_model=TwoFactorActivateResponse,
    summary="Confirm setup and activate 2FA",
)
async def activate_two_factor(
    payload: TwoFactorActivateRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TwoFactorActivateResponse:
    return await two_factor_service.activate_two_factor(db, user_id, payload.code)


@router.post(
    "/verify",
    status_code=status.HTTP_200_OK,
    response_model=TwoFactorVerifyResponse,
    summary="Verify TOTP code or single-use recovery code",
)
async def verify_two_factor(
    payload: TwoFactorVerifyRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TwoFactorVerifyResponse:
    return await two_factor_service.verify_two_factor(db, user_id, payload.code)


@router.post(
    "/disable",
    status_code=status.HTTP_200_OK,
    response_model=TwoFactorDisableResponse,
    summary="Disable 2FA requiring password confirmation",
)
async def disable_two_factor(
    payload: TwoFactorDisableRequest,
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TwoFactorDisableResponse:
    email = identity.email
    if not email:
        user = await db.get(User, user_id)
        if user:
            email = user.email
    is_google = user_id.startswith("google-oauth2|") or not user_id.startswith("auth0|")
    if not email and not is_google:
        raise BadRequestError("No se pudo resolver el correo para validar la contraseña.")

    return await two_factor_service.disable_two_factor(db, user_id, email or "", payload.password)


@router.post(
    "/recovery-codes",
    status_code=status.HTTP_200_OK,
    response_model=TwoFactorRegenerateResponse,
    summary="Regenerate single-use recovery codes",
)
async def regenerate_recovery_codes(
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TwoFactorRegenerateResponse:
    return await two_factor_service.regenerate_recovery_codes(db, user_id)

