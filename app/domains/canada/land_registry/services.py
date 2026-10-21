# Logique métier du cadastre du Québec : appelé par routes.py, appelle sources.py.

from app.domains.canada.land_registry import sources
from app.domains.canada.land_registry.entities import Lot


# Renvoie le lot correspondant au numéro, ou None si le service n'en trouve aucun ou sans contour.
def find_lot(number: str) -> Lot | None:
    for feature in sources.lot_features(number):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") in ("Polygon", "MultiPolygon"):
            properties = feature.get("properties") or {}
            return Lot(number=str(properties.get("NO_LOT") or number), geometry=geometry)
    return None
