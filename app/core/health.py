# Sonde d'état publique : indique si l'API joint la base d'apisolscore et la base métier.
# Utilisée par la supervision ou un orchestrateur ; non tracée dans l'audit.

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.database.connection import fetch_value, refonte_row

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health():
    # Requêtes minimales : réussissent si une connexion à chaque base peut être obtenue et utilisée.
    databases = {
        "apisolscore": _reachable(lambda: fetch_value("SELECT 1")),
        "refonte": _reachable(lambda: refonte_row("SELECT 1")),
    }
    statuses = {name: "ok" if reachable else "unavailable" for name, reachable in databases.items()}

    if not all(databases.values()):
        # 503 : l'API tourne mais ne peut pas servir toutes les données.
        return JSONResponse({"status": "degraded", **statuses}, status_code=503)

    return {"status": "ok", **statuses}


def _reachable(probe) -> bool:
    try:
        probe()
    except Exception:
        return False

    return True
