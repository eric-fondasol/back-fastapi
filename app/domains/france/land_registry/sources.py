# Données des services externes : le cadastre de l'IGN, via l'API Carto.

import httpx

from app.domains.france.land_registry.entities import ParcelReference

API_CARTO_PARCELS_URL = "https://apicarto.ign.fr/api/cadastre/parcelle"
# Au-delà de 10 s sans réponse, l'IGN est considéré comme injoignable.
TIMEOUT_SECONDS = 10.0


# Erreur propre au domaine, traduite en 502 par routes.py. Le service n'a pas à connaître httpx.
class LandRegistryUnavailable(Exception):
    pass


# Paris, Lyon et Marseille : le cadastre (et donc l'IDU) utilise le code INSEE de l'arrondissement
# (75105, 69382, 13202…), mais l'API Carto attend celui de la commune, avec l'arrondissement à part
# dans « code_arr » (ses trois derniers chiffres). Plages des codes d'arrondissement par commune.
MUNICIPALITIES_WITH_DISTRICTS = {
    "75056": range(75101, 75121),
    "69123": range(69381, 69390),
    "13055": range(13201, 13217),
}


# Code INSEE de la commune et code d'arrondissement à envoyer à l'API Carto ; None hors de ces trois villes.
def municipality_and_district(insee_code: str) -> tuple[str, str] | None:
    if not insee_code.isdigit():
        return None
    for municipality, districts in MUNICIPALITIES_WITH_DISTRICTS.items():
        if int(insee_code) in districts:
            return municipality, insee_code[2:]
    return None


# Paramètres d'URL attendus par l'API Carto pour une référence cadastrale (httpx les encode).
def api_carto_params(reference: ParcelReference) -> dict[str, str]:
    params = {
        "code_insee": reference.insee_code,
        "section": reference.section,
        "numero": reference.number,
        "com_abs": reference.absorbed_commune,
    }
    district = municipality_and_district(reference.insee_code)
    if district is not None:
        params["code_insee"], params["code_arr"] = district
    return params


# Interroge l'IGN et renvoie les parcelles trouvées, au format GeoJSON (liste de « features »).
def parcel_features(reference: ParcelReference) -> list[dict]:
    params = api_carto_params(reference)
    try:
        response = httpx.get(API_CARTO_PARCELS_URL, params=params, timeout=TIMEOUT_SECONDS)
        # Statut d'erreur (4xx, 5xx) renvoyé par l'IGN : lève une erreur.
        response.raise_for_status()
        # Liste vide si l'IGN ne trouve rien.
        return response.json().get("features") or []
    # Erreur réseau, délai dépassé, statut d'erreur, ou réponse qui n'est pas du JSON (ValueError).
    except (httpx.HTTPError, ValueError) as error:
        raise LandRegistryUnavailable(str(error)) from error
