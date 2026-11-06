from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.internal import CanonicalUserResponse, RelationsResponse
from app.schemas.problem import ProblemDetails
from app.services.social_service import SocialService

# Endpoints que consulta Chat desde el nodo realtime. No cuelgan de /api/v1: Kong no los expone y por eso no
# piden identidad de usuario. Su acceso se limita por red (security group del puerto publicado).
router = APIRouter(prefix="/internal", tags=["Internal"])


@router.get(
    "/users/{user_id}/canonical",
    response_model=CanonicalUserResponse,
    responses={404: {"model": ProblemDetails, "description": "Unknown user or alias"}},
)
async def canonical_user(user_id: str, db: DbSession) -> CanonicalUserResponse:
    """Chat: pasa el `X-User-Id` (puede ser un alias de login federado) al id que guarda y compara."""
    return await SocialService(db).get_canonical(user_id)


@router.get("/relations", response_model=RelationsResponse)
async def relations(actor: str, other: str, db: DbSession) -> RelationsResponse:
    """Chat: si `actor` le puede escribir a `other`. Resuelve alias. `suspended` habla de `other`."""
    return await SocialService(db).get_relations(actor, other)
