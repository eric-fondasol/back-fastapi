# Routes des aléas naturels de la France : /fr/natural-hazards/…, lues sur l'API Solscore v2.
# Protégées par le jeton (le routeur France est branché avec dependencies=protected dans main.py).

from fastapi import APIRouter

from app.domains.france.natural_hazards import services, sources
from app.domains.france.natural_hazards.schemas import CavitySearch
from app.domains.france.relay import relayed
from app.domains.france.schemas import BufferSearch, CommuneRadiusSearch, CommuneSearch

router = APIRouter(prefix="/natural-hazards", tags=["France - Natural hazards"])


# Les six aléas (retrait-gonflement des argiles, inondation, remontée de nappe, mouvements de
# terrain, sismicité, radon) en un seul objet ; 502 si aucun ne répond.
@router.post("")
def natural_hazards(search: CommuneSearch) -> dict:
    return relayed(lambda: services.natural_hazards(search.body()))


# Arrêtés de catastrophe naturelle de la commune (/fr/catnat).
@router.post("/natural-disasters")
def natural_disasters(search: CommuneRadiusSearch) -> dict:
    return relayed(lambda: sources.natural_disasters(search.body()))


# Cavités souterraines dans le rayon (/fr/cavites).
@router.post("/cavities")
def cavities(search: CavitySearch) -> dict:
    return relayed(lambda: sources.cavities(search.body()))


# Plans de prévention des risques (servitude PM1 du Géoportail de l'urbanisme) touchant le lieu
# (/fr/ppr) : documents { nom_ppr, fichier, url, zip_archive_complete }.
@router.post("/risk-plans")
def risk_plans(search: BufferSearch) -> dict:
    return relayed(lambda: sources.risk_plans(search.body()))
