# Routes de l'édition des données d'un site et de ses sondages (US-CARTE-40 à 46 du front).
# Protégées par le jeton (branchées avec dependencies=protected dans main.py).

from typing import Any

from fastapi import APIRouter, Depends

from app.core.body import json_object
from app.core.profile import Profile, current_profile
from app.domains.survey_data import services

router = APIRouter(tags=["Survey data"])


@router.get("/referentiels")
def referentiels() -> list[dict[str, Any]]:
    return [referentiel.to_json() for referentiel in services.referentiels()]


@router.get("/standards")
def standards() -> list[dict[str, Any]]:
    return [standard.to_json() for standard in services.standards()]


@router.get("/penetrometer-machine-types")
def penetrometer_machine_types() -> list[dict[str, Any]]:
    return [machine_type.to_json() for machine_type in services.penetrometer_machine_types()]


# « :path » : un identifiant de site peut contenir « / », comme un n° d'affaire. 404 site inconnu.
@router.get("/sites/{site_id:path}/reference-levels")
def site_reference_levels(site_id: str) -> dict[str, Any]:
    return services.site_reference_levels(site_id).to_json()


# Remplace tous les ouvrages du site et, si « groundElevation » est fourni et change, l'altitude du site.
# 400 corps mal formé, 404 site inconnu, 422 règle métier non respectée.
@router.put("/sites/{site_id:path}/reference-levels")
def replace_site_reference_levels(
    site_id: str, payload: dict[str, Any] = Depends(json_object), profile: Profile = Depends(current_profile)
) -> dict[str, Any]:
    return services.replace_site_reference_levels(site_id, payload, profile).to_json()
