from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import StaffIdentity, get_current_user_id
from app.clients.auth0_management import get_auth0_management_client
from app.clients.suspension_denylist import get_suspension_denylist
from app.db.session import get_db
from app.schemas.problem import ProblemDetails
from app.schemas.suspension import AccountStateFilter, PlatformUserPage, PlatformUserSummary, SuspendUserRequest
from app.services.suspension_service import SuspensionService
from app.services.user_directory_service import UserDirectoryService

# Endpoints del backoffice (solo staff). Kong exige validate("staff") en /api/v1/admin/users y acá se vuelve a
# chequear el rol con StaffIdentity (Gateway ADR-002, reglas 1 y 2).
router = APIRouter(prefix="/admin/users", tags=["Backoffice: users"])

STAFF_ERRORS = {
    status.HTTP_401_UNAUTHORIZED: {"model": ProblemDetails, "description": "Unauthenticated identity"},
    status.HTTP_403_FORBIDDEN: {"model": ProblemDetails, "description": "Not platform staff"},
}


def get_suspension_service() -> SuspensionService:
    return SuspensionService(blocker=get_auth0_management_client(), denylist=get_suspension_denylist())


Service = Annotated[SuspensionService, Depends(get_suspension_service)]
Db = Annotated[AsyncSession, Depends(get_db)]
directory_service = UserDirectoryService()


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=PlatformUserPage,
    summary="List platform accounts with filters",
    description=(
        "Staff directory. `q` matches email, username (with or without @) or display name, partially and "
        "case-insensitive. `state` filters by active or suspended. Newest accounts first."
    ),
    responses={**STAFF_ERRORS, status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ProblemDetails}},
)
async def list_users(
    _staff: StaffIdentity,
    db: Db,
    q: Annotated[str | None, Query(max_length=100, description="Email, @username or display name")] = None,
    state: Annotated[AccountStateFilter, Query(description="all, active or suspended")] = "all",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> PlatformUserPage:
    return await directory_service.search(db, q, state, page, page_size)


@router.post(
    "/suspensions",
    status_code=status.HTTP_201_CREATED,
    response_model=PlatformUserSummary,
    summary="Suspend an account at platform level",
    description=(
        "Blocks the account in Auth0 (no new logins or tokens), adds it to the Gateway denylist (its current "
        "tokens stop working) and publishes user.suspended, so Chat and Voice close its connections."
    ),
    responses={
        **STAFF_ERRORS,
        status.HTTP_400_BAD_REQUEST: {"model": ProblemDetails, "description": "Staff tried to suspend themselves"},
        status.HTTP_404_NOT_FOUND: {"model": ProblemDetails, "description": "No account matches"},
        status.HTTP_409_CONFLICT: {"model": ProblemDetails, "description": "Already suspended"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ProblemDetails, "description": "Auth0 or Redis unavailable"},
    },
)
async def suspend_user(
    payload: SuspendUserRequest,
    _staff: StaffIdentity,
    staff_user_id: Annotated[str, Depends(get_current_user_id)],
    db: Db,
    service: Service,
) -> PlatformUserSummary:
    return await service.suspend(db, payload.user, payload.reason, staff_user_id)


@router.delete(
    "/{user_id}/suspension",
    status_code=status.HTTP_200_OK,
    response_model=PlatformUserSummary,
    summary="Reactivate a suspended account",
    description="Unblocks the account in Auth0, removes it from the Gateway denylist and publishes user.reactivated.",
    responses={
        **STAFF_ERRORS,
        status.HTTP_404_NOT_FOUND: {"model": ProblemDetails, "description": "Account not found"},
        status.HTTP_409_CONFLICT: {"model": ProblemDetails, "description": "Not suspended"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ProblemDetails, "description": "Auth0 or Redis unavailable"},
    },
)
async def reactivate_user(
    user_id: str,
    _staff: StaffIdentity,
    staff_user_id: Annotated[str, Depends(get_current_user_id)],
    db: Db,
    service: Service,
) -> PlatformUserSummary:
    return await service.reactivate(db, user_id, staff_user_id)


@router.get(
    "/suspended",
    status_code=status.HTTP_200_OK,
    response_model=list[PlatformUserSummary],
    summary="List suspended accounts",
    responses=STAFF_ERRORS,
)
async def list_suspended_users(_staff: StaffIdentity, db: Db, service: Service) -> list[PlatformUserSummary]:
    return await service.list_suspended(db)
