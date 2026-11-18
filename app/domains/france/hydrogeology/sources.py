# Données des services externes : les ouvrages de la BSS et les stations ADES (niveaux des nappes),
# lus sur l'API Solscore v2. Une fonction par appel ; chacune renvoie la réponse de l'API telle quelle.

from typing import Any

from app.core import solscore_api


def bss_works(body: dict) -> Any:
    return solscore_api.post("/fr/hydrogeologie/points_bss", body)


def ades_works(body: dict) -> Any:
    return solscore_api.post("/fr/hydrogeologie/points_ades", body)


def ades_chronicle(body: dict) -> Any:
    return solscore_api.post("/fr/hydrogeologie/chroniques_ades", body)
