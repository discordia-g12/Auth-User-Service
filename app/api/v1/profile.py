from fastapi import APIRouter, File, UploadFile

from app.api.deps import CurrentUserId, DbSession
from app.schemas.profile import ProfileResponse, ProfileUpdate
from app.services.avatar_validator import validate_avatar
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/users/me", tags=["Profile"])


@router.patch("/profile", response_model=ProfileResponse)
async def update_my_profile(data: ProfileUpdate, user_id: CurrentUserId, db: DbSession):
    return await ProfileService(db).update_profile(user_id, data)


@router.patch("/profile/avatar", response_model=ProfileResponse)
async def update_my_avatar(
    user_id: CurrentUserId,
    db: DbSession,
    file: UploadFile = File(...),
):
    contents = await validate_avatar(file)
    return await ProfileService(db).upload_avatar(user_id, contents)