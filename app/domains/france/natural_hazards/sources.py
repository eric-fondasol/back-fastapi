# Données des services externes : les aléas naturels de la France, lus sur l'API Solscore v2.
# Une fonction par appel ; chacune renvoie la réponse JSON de l'API telle quelle.

from typing import Any

from app.core import solscore_api

# Les six aléas réunis par la route POST /fr/natural-hazards, des plus rapides (moins de 0,2 s) aux
# plus lents (zones inondables et mouvements de terrain, 10 à 18 s). Inondation et mouvements de
# terrain ne prennent pas de code INSEE.
HAZARD_ROUTES = {
    "rga": "/fr/alea/rga",
    "seismic": "/fr/alea/sismique",
    "radon": "/fr/alea/radon",
    "groundwater_rise": "/fr/alea/remontee_nappe",
    "flood": "/fr/alea/inondation",
    "ground_movement": "/fr/alea/mouvement_terrain",
}
WITHOUT_INSEE_CODE = {"flood", "ground_movement"}


def hazard(name: str, body: dict) -> Any:
    sent = {key: value for key, value in body.items() if not (name in WITHOUT_INSEE_CODE and key == "code_insee")}
    return solscore_api.post(HAZARD_ROUTES[name], sent)


def natural_disasters(body: dict) -> Any:
    return solscore_api.post("/fr/catnat", body)


def cavities(body: dict) -> Any:
    return solscore_api.post("/fr/cavites", body)


def risk_plans(body: dict) -> Any:
    return solscore_api.post("/fr/ppr", body)
