from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.api.deps import CurrentUserId, DbSession
from app.core.exceptions import AvatarUploadError, InvalidAvatarError, ProfileNotFoundError, UsernameTakenError
from app.schemas.profile import ProfileResponse, ProfileUpdate
from app.services.avatar_validator import validate_avatar
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/users/me", tags=["Profile"])

# Patch asi puede cambiar una parte del perfil (edicion parcial)
@router.patch("/profile", response_model=ProfileResponse)
async def update_my_profile(data: ProfileUpdate, user_id: CurrentUserId, db: DbSession):
    try:
        return await ProfileService(db).update_profile(user_id, data)
    except ProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found") from None
    except UsernameTakenError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken") from None

# Patch asi puede cambiar el avatar (edicion parcial)
@router.patch("/profile/avatar", response_model=ProfileResponse)
async def update_my_avatar(
    user_id: CurrentUserId,
    db: DbSession,
    file: UploadFile = File(...),
):
    try:
        contents = await validate_avatar(file)
        return await ProfileService(db).upload_avatar(user_id, contents)
    except InvalidAvatarError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None
    except ProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found") from None
    except AvatarUploadError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from None
