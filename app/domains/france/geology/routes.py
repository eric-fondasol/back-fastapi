# Routes de la géologie de la France : /fr/geology/…, lues sur l'API Solscore v2.
# Protégées par le jeton (le routeur France est branché avec dependencies=protected dans main.py).

from fastapi import APIRouter

from app.domains.france.geology import sources
from app.domains.france.relay import relayed
from app.domains.france.schemas import RadiusSearch

router = APIRouter(prefix="/geology", tags=["France - Geology"])


# Formation géologique du site et formations des cartes dans le rayon (/fr/geologie).
@router.post("/formations")
def formations(search: RadiusSearch) -> dict:
    return relayed(lambda: sources.formations(search.body()))
