from fastapi import APIRouter, HTTPException

from app.domains.france.land_registry import services
from app.domains.france.land_registry.entities import Parcel
from app.domains.france.land_registry.schemas import ParcelCollection, ParcelFeature, ParcelProperties, ParcelSearch
from app.domains.france.land_registry.sources import LandRegistryUnavailable

router = APIRouter(prefix="/land-registry", tags=["France - Land registry"])


@router.post("/parcels", response_model=ParcelCollection)
def find_parcel(search: ParcelSearch) -> ParcelCollection:
    reference = search.reference()
    try:
        parcel = services.find_parcel(reference)
    except LandRegistryUnavailable as error:
        raise HTTPException(status_code=502, detail="Cadastre de l'IGN injoignable") from error
    if parcel is None:
        raise HTTPException(status_code=404, detail=f"Parcelle {reference.idu} introuvable")
    return ParcelCollection(features=[_feature(parcel)])


def _feature(parcel: Parcel) -> ParcelFeature:
    return ParcelFeature(
        geometry=parcel.geometry,
        properties=ParcelProperties(
            idu=parcel.idu,
            code_insee=parcel.insee_code,
            nom_com=parcel.commune_name,
            com_abs=parcel.absorbed_commune,
            section=parcel.section,
            numero=parcel.number,
            feuille=parcel.sheet,
            contenance=parcel.official_area_m2,
            superficie_m2=parcel.computed_area_m2,
        ),
    )
