from fastapi import APIRouter

from app.api.v1 import profile, users

api_router = APIRouter()
api_router.include_router(profile.router)
api_router.include_router(users.router)

