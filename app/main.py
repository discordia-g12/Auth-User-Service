from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import internal
from app.api.v1 import api_router
from app.core.exceptions import register_exception_handlers
from app.core.logger import get_logger, setup_logging
from app.db.session import get_db

logger = get_logger(__name__)


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
app.include_router(internal.router)


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
    """Readiness probe: validates critical dependencies such as the database are operational.

    The failure cause is logged, never returned: driver messages can leak host names, users,
    database names or schema details to whoever can reach the probe.
    """
    try:
        await db.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        # OSError covers connection-level failures (refused, DNS, timeout) the driver may raise unwrapped.
        logger.exception("readiness_check_failed", dependency="database")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready"}
    return {"status": "ready"}
