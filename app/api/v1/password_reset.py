from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.auth0 import build_auth0_password_reset_client
from app.core.config import settings
from app.db.session import get_db
from app.schemas.password_reset import PasswordResetAcceptedResponse, PasswordResetRequestBody
from app.schemas.problem import ProblemDetails
from app.services.password_reset_service import PasswordResetService

router = APIRouter()


def get_password_reset_service() -> PasswordResetService:
    return PasswordResetService(
        sender=build_auth0_password_reset_client(),
        max_requests=settings.password_reset_max_requests,
        window_seconds=settings.password_reset_window_seconds,
    )


@router.post(
    "/password-reset",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PasswordResetAcceptedResponse,
    summary="Request a password reset email",
    description=(
        "Public endpoint (no JWT). Auth0 emails a single-use link that expires in 1 hour. The response is the "
        "same whether or not the email is registered. Limited per email here and per IP in the Gateway."
    ),
    responses={
        status.HTTP_202_ACCEPTED: {"model": PasswordResetAcceptedResponse, "description": "Request accepted"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ProblemDetails, "description": "Invalid email format"},
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "model": ProblemDetails,
            "description": "Too many requests for this email (see Retry-After)",
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ProblemDetails, "description": "Identity provider unavailable"},
    },
)
async def request_password_reset(
    payload: PasswordResetRequestBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[PasswordResetService, Depends(get_password_reset_service)],
) -> PasswordResetAcceptedResponse:
    await service.request_reset(db, payload.email)
    return PasswordResetAcceptedResponse()
