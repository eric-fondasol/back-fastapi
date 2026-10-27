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
def _query(params: dict[str, str]) -> list[dict]:
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


# Champs et format communs : numéro de lot et contour, rendu en WGS 84 comme le cadastre France.
ANSWER = {"outFields": "NO_LOT", "returnGeometry": "true", "outSR": "4326", "f": "geojson"}

# Contour simplifié à 0,000005° près (environ 50 cm) : un grand lot rural pèse sinon jusqu'à 170 Ko.
MAX_ALLOWABLE_OFFSET_DEGREES = "0.000005"


# Lot portant ce numéro.
def lot_features(number: str) -> list[dict]:
    # Le numéro ne contient que des chiffres et des espaces (schemas.py) : pas d'apostrophe à échapper.
    return _query({"where": f"NO_LOT = '{number}'", **ANSWER})


# Lot qui contient ce point (clic sur la carte).
def lot_features_at(longitude: float, latitude: float) -> list[dict]:
    return _query(
        {
            "geometry": f"{longitude},{latitude}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "maxAllowableOffset": MAX_ALLOWABLE_OFFSET_DEGREES,
            **ANSWER,
        }
    )
