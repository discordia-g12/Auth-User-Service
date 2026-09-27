from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import api_router
from app.db.session import get_db

from app.core.exceptions import register_exception_handlers
from app.core.logger import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    yield


app = FastAPI(
    title="Discordia Auth & User Service",
    description="User entity, profile management, and domain events service for Discordia.",
    version="1.0.0",
    lifespan=lifespan,
)

register_exception_handlers(app)
app.include_router(api_router, prefix="/api/v1")

@app.get("/", tags=["Root"])
def read_root():
    """Informational root endpoint."""
    return {"service": "Auth & User Service", "version": "1.0.0"}


@app.get("/livez", tags=["Health"])
async def liveness_probe():
    """Liveness probe: verifies process is alive and HTTP server responds (no external I/O)."""
    return {"status": "alive"}


@app.get("/readyz", tags=["Health"])
async def readiness_probe(response: Response, db: Annotated[AsyncSession, Depends(get_db)]):
    """Readiness probe: validates critical dependencies such as the database are operational."""
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except SQLAlchemyError as e:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "detail": str(e)}
