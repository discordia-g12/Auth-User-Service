from fastapi import APIRouter

from app.api.v1 import profile
from app.api.v1.password_reset import router as password_reset_router
from app.api.v1.users import router as users_router

api_router = APIRouter()
api_router.include_router(users_router, prefix="/users", tags=["Users"])
api_router.include_router(password_reset_router, prefix="/auth", tags=["Password reset"])
api_router.include_router(profile.router)