# Données des services externes : documents d'urbanisme du Géoportail de l'urbanisme, lus sur l'API
# Solscore v2 et renvoyés tels quels.

from typing import Any

from app.core import solscore_api


def urban_plans(body: dict) -> Any:
    return solscore_api.post("/fr/plu", body)
