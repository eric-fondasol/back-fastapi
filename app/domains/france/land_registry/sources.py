import httpx

from app.domains.france.land_registry.entities import ParcelReference

API_CARTO_PARCELS_URL = "https://apicarto.ign.fr/api/cadastre/parcelle"
TIMEOUT_SECONDS = 10.0


class LandRegistryUnavailable(Exception):
    pass


def parcel_features(reference: ParcelReference) -> list[dict]:
    params = {
        "code_insee": reference.insee_code,
        "section": reference.section,
        "numero": reference.number,
        "com_abs": reference.absorbed_commune,
    }
    try:
        response = httpx.get(API_CARTO_PARCELS_URL, params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json().get("features") or []
    except (httpx.HTTPError, ValueError) as error:
        raise LandRegistryUnavailable(str(error)) from error
