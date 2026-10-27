# Appels aux services des couches vectorielles du catalogue : WFS (GML ou GeoJSON) et API GeoJSON
# (Hub'Eau). Le back les appelle à la place du navigateur : certains ne répondent qu'en HTTP
# (ws.carmencarto.fr) ou ne savent pas produire de GeoJSON.

import json
from typing import Any

import httpx

from app.domains.layer_catalog import gml
from app.domains.layer_catalog.geometry import Bbox, swap_axes

# Au-delà de 20 s sans réponse, le service est considéré comme injoignable.
TIMEOUT_SECONDS = 20.0
# Plafond d'objets demandés au service pour un écran : au-delà, la carte deviendrait illisible et lente.
MAX_FEATURES = 3000
# Réponse brute plafonnée : un service qui renvoie davantage pour un écran est mal paramétré (zoom minimal trop bas).
MAX_RESPONSE_BYTES = 40 * 1024 * 1024


class FeatureServiceUnavailable(Exception):
    pass


def _get(url: str, params: dict[str, Any]) -> httpx.Response:
    try:
        response = httpx.get(url, params=params, timeout=TIMEOUT_SECONDS, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise FeatureServiceUnavailable(str(error)) from error
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise FeatureServiceUnavailable(f"Réponse de {len(response.content)} octets, trop volumineuse")
    return response


def _json_features(content: bytes) -> list[dict[str, Any]]:
    try:
        document = json.loads(content)
    except ValueError as error:
        raise FeatureServiceUnavailable("Réponse GeoJSON illisible") from error
    found = document.get("features") if isinstance(document, dict) else None
    if not isinstance(found, list):
        raise FeatureServiceUnavailable("Réponse sans « features »")
    return [feature for feature in found if isinstance(feature, dict)]


# WFS : BBOX et coordonnées dans l'ordre déclaré par params.axisOrder (« latlon » pour MapServer en
# WFS 1.1.0 et EPSG:4326, « lonlat » sinon). Sortie GML convertie, ou GeoJSON lu tel quel.
def wfs_features(url: str, params: dict[str, Any], bbox: Bbox) -> list[dict[str, Any]]:
    west, south, east, north = bbox
    version = str(params.get("version", "2.0.0"))
    srs = str(params.get("srsName", "EPSG:4326"))
    latlon = params.get("axisOrder") == "latlon"
    corners = (south, west, north, east) if latlon else (west, south, east, north)
    output = str(params.get("outputFormat", "GML2"))
    query = {
        "SERVICE": "WFS",
        "REQUEST": "GetFeature",
        "VERSION": version,
        "TYPENAMES" if version.startswith("2") else "TYPENAME": params["typeName"],
        "SRSNAME": srs,
        "OUTPUTFORMAT": output,
        "BBOX": ",".join(str(value) for value in corners) + f",{srs}",
        "COUNT" if version.startswith("2") else "MAXFEATURES": MAX_FEATURES,
    }
    content = _get(url, query).content
    if "json" in output.lower():
        found = _json_features(content)
    else:
        try:
            found = gml.features(content)
        except gml.GmlError as error:
            raise FeatureServiceUnavailable(str(error)) from error
    if latlon:
        found = [{**feature, "geometry": swap_axes(feature.get("geometry"))} for feature in found]
    return found


class TileNotFound(Exception):
    pass


# Tuile WMTS (GetTile, KVP) d'un service privé, demandée avec la clé d'API. Une tuile hors de la zone
# couverte ou du niveau de zoom servi (404 ou 400 du service) est TileNotFound ; un refus de la clé
# (401, 403) ou une panne, FeatureServiceUnavailable.
def wmts_tile(url: str, params: dict[str, Any], api_key: str, z: int, x: int, y: int) -> tuple[bytes, str]:
    query = {
        "SERVICE": "WMTS",
        "REQUEST": "GetTile",
        "VERSION": "1.0.0",
        "LAYER": params["layer"],
        "STYLE": params["style"],
        "TILEMATRIXSET": params["tileMatrixSet"],
        "FORMAT": params.get("format", "image/png"),
        "TILEMATRIX": z,
        "TILEROW": y,
        "TILECOL": x,
        "apikey": api_key,
    }
    try:
        response = httpx.get(url, params=query, timeout=TIMEOUT_SECONDS, follow_redirects=True)
    except httpx.HTTPError as error:
        raise FeatureServiceUnavailable(type(error).__name__) from error
    if response.status_code in (400, 404):
        raise TileNotFound()
    # Message sans l'URL : elle contient la clé, et l'erreur finit dans le journal.
    if response.status_code != 200:
        raise FeatureServiceUnavailable(f"Tuile refusée par le service ({response.status_code})")
    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        raise FeatureServiceUnavailable(f"Réponse qui n'est pas une image ({content_type or 'sans type'})")
    return response.content, content_type


# API GeoJSON : chaque paramètre est repris, « {bbox} » remplacé par « ouest,sud,est,nord », la taille
# plafonnée par MAX_FEATURES.
def geojson_features(url: str, params: dict[str, Any], bbox: Bbox) -> list[dict[str, Any]]:
    extent = ",".join(str(value) for value in bbox)
    query = {key: str(value).replace("{bbox}", extent) for key, value in params.items()}
    if "size" in query:
        query["size"] = str(min(int(query["size"]), MAX_FEATURES))
    return _json_features(_get(url, query).content)[:MAX_FEATURES]
