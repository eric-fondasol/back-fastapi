# Routes du cadastre du Luxembourg : /lu/land-registry/…
# Protégées par le jeton (le routeur Luxembourg est branché avec dependencies=protected dans main.py).

from fastapi import APIRouter, HTTPException

from app.domains.luxembourg.land_registry import services
from app.domains.luxembourg.land_registry.schemas import ParcelCollection, ParcelFeature, ParcelLocation, ParcelProperties
from app.domains.luxembourg.land_registry.sources import LandRegistryUnavailable

router = APIRouter(prefix="/land-registry", tags=["Luxembourg - Land registry"])


# Parcelle qui contient le point cliqué ou survolé sur la carte, pour la sélection. 404 hors parcelle.
@router.post("/parcels/at", response_model=ParcelCollection)
def parcel_at(location: ParcelLocation) -> ParcelCollection:
    try:
        parcel = services.parcel_at(location.longitude, location.latitude)
    except LandRegistryUnavailable as error:
        # 502 : c'est le géoportail qui est en défaut, pas la demande.
        raise HTTPException(status_code=502, detail="Cadastre du Luxembourg injoignable") from error
    if parcel is None:
        raise HTTPException(status_code=404, detail="Aucune parcelle à cet endroit")
    properties = ParcelProperties(
        reference=parcel.reference,
        number=parcel.number,
        area_m2=parcel.area_m2,
        municipality=parcel.zoning.municipality,
        section=parcel.zoning.section,
        section_name=parcel.zoning.section_name,
    )
    return ParcelCollection(features=[ParcelFeature(geometry=parcel.geometry, properties=properties)])
