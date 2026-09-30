from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.database.connection import fetch_value

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health():
    try:
        fetch_value("SELECT 1")
    except Exception:
        return JSONResponse({"status": "degraded", "apisolscore": "unavailable"}, status_code=503)

    return {"status": "ok", "apisolscore": "ok"}
