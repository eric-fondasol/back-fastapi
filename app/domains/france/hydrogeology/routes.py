# Routes de l'hydrogéologie de la France : /fr/hydrogeology/…, lues sur l'API Solscore v2.
# Protégées par le jeton (le routeur France est branché avec dependencies=protected dans main.py).

from fastapi import APIRouter

from app.domains.france.hydrogeology import sources
from app.domains.france.hydrogeology.schemas import BssSearch, ChronicleSearch
from app.domains.france.relay import relayed
from app.domains.france.schemas import PlaceSearch

router = APIRouter(prefix="/hydrogeology", tags=["France - Hydrogeology"])


# Ouvrages de la Banque du sous-sol dans le rayon (/fr/hydrogeologie/points_bss).
@router.post("/bss-works")
def bss_works(search: BssSearch) -> dict:
    return relayed(lambda: sources.bss_works(search.body()))


# Stations piézométriques ADES autour du lieu (/fr/hydrogeologie/points_ades, environ 20 km).
@router.post("/ades-works")
def ades_works(search: PlaceSearch) -> dict:
    return relayed(lambda: sources.ades_works(search.body()))


# Mesures d'une station ADES (/fr/hydrogeologie/chroniques_ades).
@router.post("/ades-chronicles")
def ades_chronicle(search: ChronicleSearch) -> dict:
    return relayed(lambda: sources.ades_chronicle(search.body()))
