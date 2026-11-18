# Données des services externes : la géologie de la France (carte géologique au 1/50 000 du BRGM),
# lue sur l'API Solscore v2 et renvoyée telle quelle.

from typing import Any

from app.core import solscore_api


def formations(body: dict) -> Any:
    return solscore_api.post("/fr/geologie", body)
