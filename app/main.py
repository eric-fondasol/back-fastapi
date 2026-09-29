import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import ex
from app.auth import current_user, dev_token
from app.connexions import base, base_apisolscore, cache


@asynccontextmanager
async def demarrage(_: FastAPI):
    dev_token()
    yield


app = FastAPI(lifespan=demarrage)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origine for origine in os.getenv("CORS_ORIGINS", "").split(",") if origine],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(ex.router, dependencies=[Depends(current_user)])


@app.get("/api/health")
def sante():
    etat = {"postgis": "indisponible", "apisolscore": "indisponible", "redis": "indisponible"}

    try:
        with base.connect() as connexion:
            etat["postgis"] = connexion.execute(text("SELECT postgis_version()")).scalar()
    except Exception:
        pass

    try:
        with base_apisolscore.connect() as connexion:
            connexion.execute(text("SELECT 1"))
            etat["apisolscore"] = "ok"
    except Exception:
        pass

    try:
        cache.ping()
        etat["redis"] = "ok"
    except Exception:
        pass

    disponible = "indisponible" not in etat.values()

    return JSONResponse({"status": "ok" if disponible else "degraded", **etat}, status_code=200 if disponible else 503)
