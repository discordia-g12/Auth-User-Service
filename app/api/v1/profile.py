from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUserId, DbSession
from app.schemas.profile import ProfileResponse, ProfileUpdate
from app.services.profile_service import ProfileNotFoundError, ProfileService, UsernameTakenError

router = APIRouter(prefix="/users/me", tags=["Profile"])

# Patch asi puede cambiar una parte del perfil (edición parcial)
@router.patch("/profile", response_model=ProfileResponse)
async def update_my_profile(data: ProfileUpdate, user_id: CurrentUserId, db: DbSession):
    try:
        return await ProfileService(db).update_profile(user_id, data)
    except ProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found") from None
    except UsernameTakenError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken") from None
