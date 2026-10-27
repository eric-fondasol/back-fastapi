# Route du catalogue des couches : GET /layer-catalog. Contrat attendu par le front (ADR-0043,
# docs/features/map.md). Protégée par le jeton (branchée avec dependencies=protected dans main.py).

from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query, Response

from app.domains.layer_catalog import services
from app.domains.layer_catalog.geometry import Bbox
from app.domains.layer_catalog.sources import FeatureServiceUnavailable, TileNotFound

router = APIRouter(tags=["Layer catalog"])


# { "categories": [{ "code": "geologie", "label": { "fr": "Géologie", "en": "Geology" } }],
#   "layers": [{ "code": "fr-geologie", "category": "geologie", "country": "fr", "label": {…}, "kind": "wms", … }] }
@router.get("/layer-catalog")
def layer_catalog() -> dict[str, Any]:
    return services.catalog()


# Emprise la plus large acceptée, en degrés : bien plus qu'un écran au zoom minimal d'une couche
# vectorielle ; au-delà, la demande ne vient pas de la carte.
MAX_BBOX_SPAN_DEGREES = 30.0
MAX_ZOOM = 22


def _bbox(value: str) -> Bbox:
    try:
        west, south, east, north = (float(part) for part in value.split(","))
    except ValueError as error:
        raise HTTPException(status_code=400, detail="bbox attendue : ouest,sud,est,nord") from error
    valid = (
        -180 <= west < east <= 180
        and -90 <= south < north <= 90
        and east - west <= MAX_BBOX_SPAN_DEGREES
        and north - south <= MAX_BBOX_SPAN_DEGREES
    )
    if not valid:
        raise HTTPException(status_code=400, detail="bbox hors limites")
    return west, south, east, north


# Objets d'une couche vectorielle (WFS ou GeoJSON) dans l'emprise affichée, en GeoJSON allégé pour le
# zoom (ADR-0045 du front) : { "type": "FeatureCollection", "features": [...], "truncated": bool }.
@router.get("/layer-catalog/{code}/features")
def layer_features(code: str, bbox: str = Query(...), zoom: int = Query(..., ge=0, le=MAX_ZOOM)) -> dict[str, Any]:
    try:
        return services.feature_collection(code, _bbox(bbox), zoom)
    except services.UnknownFeatureLayer as error:
        raise HTTPException(status_code=404, detail=f"Couche vectorielle {code} inconnue") from error
    except FeatureServiceUnavailable as error:
        # 502 : c'est le service de la couche qui est en défaut, pas la demande.
        raise HTTPException(status_code=502, detail=f"Service de la couche {code} injoignable") from error


# Une tuile change rarement : le navigateur la garde un jour, sans la partager (réponse authentifiée).
TILE_CACHE_CONTROL = "private, max-age=86400"


# Tuile d'une couche relayée (params.relayed, ADR-0046 du front) : le back la demande au service privé
# avec sa clé d'API, que le navigateur ne voit jamais. Image du service, ou 404 hors couverture.
@router.get("/layer-catalog/{code}/tiles/{z}/{x}/{y}")
def layer_tile(code: str, z: int = Path(ge=0, le=MAX_ZOOM), x: int = Path(ge=0), y: int = Path(ge=0)) -> Response:
    if x >= 2**z or y >= 2**z:
        raise HTTPException(status_code=400, detail="Tuile hors de la grille")
    try:
        content, content_type = services.tile(code, z, x, y)
    except services.UnknownTileLayer as error:
        raise HTTPException(status_code=404, detail=f"Couche relayée {code} inconnue") from error
    except TileNotFound as error:
        raise HTTPException(status_code=404, detail="Tuile absente") from error
    except FeatureServiceUnavailable as error:
        raise HTTPException(status_code=502, detail=f"Service de la couche {code} injoignable") from error
    return Response(content=content, media_type=content_type, headers={"Cache-Control": TILE_CACHE_CONTROL})
