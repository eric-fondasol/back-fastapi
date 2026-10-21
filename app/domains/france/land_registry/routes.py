# Routes du cadastre France : /fr/land-registry/…
# Protégées par le jeton (le routeur France est branché avec dependencies=protected dans main.py).

from fastapi import APIRouter, HTTPException

from app.domains.france.land_registry import services
from app.domains.france.land_registry.entities import Parcel
from app.domains.france.land_registry.schemas import ParcelCollection, ParcelFeature, ParcelProperties, ParcelSearch
from app.domains.france.land_registry.sources import LandRegistryUnavailable

router = APIRouter(prefix="/land-registry", tags=["France - Land registry"])


# Cherche une parcelle par sa référence cadastrale. Le corps est validé par ParcelSearch (422 si invalide).
@router.post("/parcels", response_model=ParcelCollection)
def find_parcel(search: ParcelSearch) -> ParcelCollection:
    # Référence normalisée (section, numéro et commune absorbée complétés par des zéros).
    reference = search.reference()
    try:
        parcel = services.find_parcel(reference)
    except LandRegistryUnavailable as error:
        # 502 : c'est le service de l'IGN qui est en défaut, pas la demande.
        raise HTTPException(status_code=502, detail="Cadastre de l'IGN injoignable") from error
    # Aucune parcelle ne correspond à cette référence.
    if parcel is None:
        raise HTTPException(status_code=404, detail=f"Parcelle {reference.idu} introuvable")
    # Réponse en GeoJSON, avec une seule parcelle.
    return ParcelCollection(features=[_feature(parcel)])


# Convertit l'entité Parcel en réponse pour le front : les noms des propriétés reprennent ceux du
# cadastre (code_insee, nom_com, contenance…), attendus par le front.
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
