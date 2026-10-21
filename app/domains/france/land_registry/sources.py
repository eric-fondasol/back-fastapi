# Données des services externes : le cadastre de l'IGN, via l'API Carto.

import httpx

from app.domains.france.land_registry.entities import ParcelReference

API_CARTO_PARCELS_URL = "https://apicarto.ign.fr/api/cadastre/parcelle"
# Au-delà de 10 s sans réponse, l'IGN est considéré comme injoignable.
TIMEOUT_SECONDS = 10.0


# Erreur propre au domaine, traduite en 502 par routes.py. Le service n'a pas à connaître httpx.
class LandRegistryUnavailable(Exception):
    pass


# Interroge l'IGN et renvoie les parcelles trouvées, au format GeoJSON (liste de « features »).
def parcel_features(reference: ParcelReference) -> list[dict]:
    # Paramètres d'URL attendus par l'API Carto (httpx les encode).
    params = {
        "code_insee": reference.insee_code,
        "section": reference.section,
        "numero": reference.number,
        "com_abs": reference.absorbed_commune,
    }
    try:
        response = httpx.get(API_CARTO_PARCELS_URL, params=params, timeout=TIMEOUT_SECONDS)
        # Statut d'erreur (4xx, 5xx) renvoyé par l'IGN : lève une erreur.
        response.raise_for_status()
        # Liste vide si l'IGN ne trouve rien.
        return response.json().get("features") or []
    # Erreur réseau, délai dépassé, statut d'erreur, ou réponse qui n'est pas du JSON (ValueError).
    except (httpx.HTTPError, ValueError) as error:
        raise LandRegistryUnavailable(str(error)) from error
