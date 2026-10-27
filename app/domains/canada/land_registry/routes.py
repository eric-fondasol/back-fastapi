# Routes du cadastre du Québec : /ca/land-registry/…
# Protégées par le jeton (le routeur Canada est branché avec dependencies=protected dans main.py).

from fastapi import APIRouter, HTTPException

from app.domains.canada.land_registry import services
from app.domains.canada.land_registry.entities import Lot
from app.domains.canada.land_registry.schemas import LotCollection, LotFeature, LotLocation, LotProperties, LotSearch
from app.domains.canada.land_registry.sources import LandRegistryUnavailable

router = APIRouter(prefix="/land-registry", tags=["Canada - Land registry"])


# Cherche un lot par son numéro. Le corps est validé par LotSearch (422 si invalide).
@router.post("/lots", response_model=LotCollection)
def find_lot(search: LotSearch) -> LotCollection:
    number = search.number()
    try:
        lot = services.find_lot(number)
    except LandRegistryUnavailable as error:
        # 502 : c'est le service du Québec qui est en défaut, pas la demande.
        raise HTTPException(status_code=502, detail="Cadastre du Québec injoignable") from error
    if lot is None:
        raise HTTPException(status_code=404, detail=f"Lot {number} introuvable")
    return _collection(lot)


# Lot qui contient le point cliqué sur la carte, pour la sélection de parcelles. 404 hors du cadastre rénové.
@router.post("/lots/at", response_model=LotCollection)
def lot_at(location: LotLocation) -> LotCollection:
    try:
        lot = services.lot_at(location.longitude, location.latitude)
    except LandRegistryUnavailable as error:
        raise HTTPException(status_code=502, detail="Cadastre du Québec injoignable") from error
    if lot is None:
        raise HTTPException(status_code=404, detail="Aucun lot à cet endroit")
    return _collection(lot)


def _collection(lot: Lot) -> LotCollection:
    return LotCollection(features=[LotFeature(geometry=lot.geometry, properties=LotProperties(no_lot=lot.number, area_m2=lot.area_m2()))])
