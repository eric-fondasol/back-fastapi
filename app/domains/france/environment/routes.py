# Routes de l'environnement du site en France : /fr/environment/…, lues sur l'API Solscore v2, sauf les sites
# CASIAS, BASOL et SIS, lus en base (sites.py).
# Protégées par le jeton (le routeur France est branché avec dependencies=protected dans main.py).

from fastapi import APIRouter

from app.database.connection import refonte_transaction
from app.domains.france.environment import sites, sources
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


# Sites CASIAS (anciens sites industriels et activités de service) dans le rayon, triés par distance, lus dans la
# table casias_sites, celle des couches CASIAS (voir sites.py).
@router.post("/casias-sites")
def casias_sites(search: RadiusSearch) -> dict:
    with refonte_transaction() as connection:
        return sites.sites_within(connection, sites.CASIAS, search)


# Sites BASOL (pollution des sols appelant une action des pouvoirs publics) dans le rayon, triés par distance, lus
# dans la table basol_sites, celle des couches BASOL (voir sites.py).
@router.post("/basol-sites")
def basol_sites(search: RadiusSearch) -> dict:
    with refonte_transaction() as connection:
        return sites.sites_within(connection, sites.BASOL, search)


# Secteurs d'information sur les sols (SIS) dans le rayon, triés par distance, lus dans la table sis_sites, celle
# de la couche SIS (voir sites.py).
@router.post("/sis-sites")
def sis_sites(search: RadiusSearch) -> dict:
    with refonte_transaction() as connection:
        return sites.sites_within(connection, sites.SIS, search)
