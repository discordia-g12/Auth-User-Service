from fastapi import APIRouter

from app.api.v1 import admin_users, password_reset, profile, two_factor, users

api_router = APIRouter()
api_router.include_router(users.router)
api_router.include_router(admin_users.router)
api_router.include_router(two_factor.router)
api_router.include_router(profile.router)
api_router.include_router(password_reset.router)
