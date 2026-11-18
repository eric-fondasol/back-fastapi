# Routes de l'environnement du site en France : /fr/environment/…, lues sur l'API Solscore v2.
# Protégées par le jeton (le routeur France est branché avec dependencies=protected dans main.py).

from fastapi import APIRouter

from app.domains.france.environment import sources
from app.domains.france.relay import relayed
from app.domains.france.schemas import PlaceSearch, RadiusSearch

router = APIRouter(prefix="/environment", tags=["France - Environment"])


# Commune touchée par les bombardements de 1914-1918 ou de 1939-1945 (/fr/risque_pyrotechnique).
@router.post("/pyrotechnics")
def pyrotechnics(search: PlaceSearch) -> dict:
    return relayed(lambda: sources.pyrotechnics(search.body()))


# Fouilles archéologiques de l'INRAP dans le rayon (/fr/inrap).
@router.post("/archaeological-excavations")
def archaeological_excavations(search: RadiusSearch) -> dict:
    return relayed(lambda: sources.archaeological_excavations(search.body()))


# Sites CASIAS (anciens sites industriels et activités de service) dans le rayon, triés par
# distance (/fr/casias, extrait CASIAS.gpkg chargé par l'API Solscore v2).
@router.post("/casias-sites")
def casias_sites(search: RadiusSearch) -> dict:
    return relayed(lambda: sources.casias_sites(search.body()))
