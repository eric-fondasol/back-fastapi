# Données des services externes : risque pyrotechnique (dommages de guerre), fouilles
# archéologiques de l'INRAP et sites CASIAS, lus sur l'API Solscore v2 et renvoyés tels quels.

from typing import Any

from app.core import solscore_api


def pyrotechnics(body: dict) -> Any:
    return solscore_api.post("/fr/risque_pyrotechnique", body)


def archaeological_excavations(body: dict) -> Any:
    return solscore_api.post("/fr/inrap", body)


def casias_sites(body: dict) -> Any:
    return solscore_api.post("/fr/casias", body)
