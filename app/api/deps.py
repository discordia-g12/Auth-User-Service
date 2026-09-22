from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

DbSession = Annotated[AsyncSession, Depends(get_db)]


# Devuelve el id del usuario autenticado, va a estar en el header. 
# Con Header() va a buscar en el header y no en la query string
# Con Depends() va a ejecutar la función antes de ejecutar la ruta
async def get_current_user_id(x_user_id: Annotated[str | None, Header()] = None):
    if not x_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return x_user_id


CurrentUserId = Annotated[str, Depends(get_current_user_id)]
