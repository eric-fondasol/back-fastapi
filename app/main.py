from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import ex
from app.connexions import base, base_apisolscore, cache

app = FastAPI()
app.include_router(ex.router)


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
