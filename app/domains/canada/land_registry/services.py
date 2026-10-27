# Logique métier du cadastre du Québec : appelé par routes.py, appelle sources.py.

from app.domains.canada.land_registry import sources
from app.domains.canada.land_registry.entities import Lot


# Premier lot avec un contour parmi les objets renvoyés par le service, ou None.
def _first_lot(features: list[dict], number: str | None = None) -> Lot | None:
    for feature in features:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") in ("Polygon", "MultiPolygon"):
            properties = feature.get("properties") or {}
            found = properties.get("NO_LOT") or number
            if found:
                return Lot(number=str(found), geometry=geometry)
    return None


# Renvoie le lot correspondant au numéro, ou None si le service n'en trouve aucun ou sans contour.
def find_lot(number: str) -> Lot | None:
    return _first_lot(sources.lot_features(number), number)


# Renvoie le lot qui contient ce point (clic sur la carte), ou None hors du cadastre rénové.
def lot_at(longitude: float, latitude: float) -> Lot | None:
    return _first_lot(sources.lot_features_at(longitude, latitude))
