from fastapi import Depends, FastAPI, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

app = FastAPI(title="Auth User Service")

@app.get("/")
def read_root():
    return {"message": "Welcome to Auth User Service API"}

@app.get("/livez", tags=["Health"])
async def liveness_probe():
    """Valida únicamente que el servidor HTTP responde."""
    return {"status": "alive"}

@app.get("/readyz", tags=["Health"])
async def readiness_probe(response: Response, db: AsyncSession = Depends(get_db)):
    """Valida dependencias críticas como la BD."""
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as e:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "detail": str(e)}