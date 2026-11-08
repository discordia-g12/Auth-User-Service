from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.user_repository import UserRepository
from app.schemas.suspension import AccountStateFilter, PlatformUserPage
from app.services.suspension_service import to_summary


class UserDirectoryService:
    """Staff directory of platform accounts ("Ver listado de usuarios con filtros"): search by email, username
    or display name, and filter by state. Only staff reaches it (Kong validate("staff") + require_staff)."""

    def __init__(self, user_repo: UserRepository | None = None):
        self.user_repo = user_repo or UserRepository()

    async def search(
        self,
        session: AsyncSession,
        query: str | None,
        state: AccountStateFilter,
        page: int,
        page_size: int,
    ) -> PlatformUserPage:
        users, total = await self.user_repo.search_users(
            session, query, state, limit=page_size, offset=(page - 1) * page_size
        )
        return PlatformUserPage(items=[to_summary(user) for user in users], total=total, page=page, page_size=page_size)
