# Données du service externe : le « Cadastre allégé » du gouvernement du Québec (ArcGIS, public, sans clé),
# qui diffuse les lots du cadastre rénové (numéro et contour), mis à jour tous les deux mois.

import httpx

# Adresse fixe : le numéro de lot est le seul paramètre venu de l'utilisateur, déjà contrôlé par schemas.py.
CADASTRE_ALLEGE_QUERY_URL = (
    "https://geo.environnement.gouv.qc.ca/donnees/rest/services/Reference/Cadastre_allege/MapServer/0/query"
)
# Au-delà de 10 s sans réponse, le service est considéré comme injoignable.
TIMEOUT_SECONDS = 10.0


# Erreur propre au domaine, traduite en 502 par routes.py. Le service n'a pas à connaître httpx.
class LandRegistryUnavailable(Exception):
    pass


# Interroge le service et renvoie les lots trouvés, au format GeoJSON (liste de « features »).
def lot_features(number: str) -> list[dict]:
    params = {
        # Le numéro ne contient que des chiffres et des espaces (schemas.py) : pas d'apostrophe à échapper.
        "where": f"NO_LOT = '{number}'",
        "outFields": "NO_LOT",
        "returnGeometry": "true",
        # Contour rendu en WGS 84, comme le cadastre France.
        "outSR": "4326",
        "f": "geojson",
    }
    try:
        response = httpx.get(CADASTRE_ALLEGE_QUERY_URL, params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        body = response.json()
    # Erreur réseau, délai dépassé, statut d'erreur, ou réponse qui n'est pas du JSON (ValueError).
    except (httpx.HTTPError, ValueError) as error:
        raise LandRegistryUnavailable(str(error)) from error

    # ArcGIS signale ses erreurs avec un statut 200 et un objet « error ».
    if not isinstance(body, dict) or "error" in body:
        raise LandRegistryUnavailable(str(body)[:200])

    return body.get("features") or []
