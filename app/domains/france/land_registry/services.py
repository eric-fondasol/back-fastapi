import math

from app.domains.france.land_registry import sources
from app.domains.france.land_registry.entities import Parcel, ParcelReference

EARTH_RADIUS_M = 6378137.0


def find_parcel(reference: ParcelReference) -> Parcel | None:
    features = sources.parcel_features(reference)
    return to_parcel(features[0]) if features else None


def to_parcel(feature: dict) -> Parcel:
    properties = feature.get("properties") or {}
    geometry = feature.get("geometry") or {}
    return Parcel(
        idu=str(properties.get("idu", "")),
        insee_code=str(properties.get("code_insee", "")),
        commune_name=str(properties.get("nom_com", "")),
        absorbed_commune=str(properties.get("com_abs", "")),
        section=str(properties.get("section", "")),
        number=str(properties.get("numero", "")),
        sheet=properties.get("feuille"),
        official_area_m2=properties.get("contenance"),
        computed_area_m2=round(geodesic_area_m2(geometry), 1),
        geometry=geometry,
    )


def geodesic_area_m2(geometry: dict) -> float:
    coordinates = geometry.get("coordinates") or []
    polygons = coordinates if geometry.get("type") == "MultiPolygon" else [coordinates]
    return sum(polygon_area(polygon) for polygon in polygons)


def polygon_area(rings: list) -> float:
    if not rings:
        return 0.0
    outer, *holes = rings
    return abs(ring_area(outer)) - sum(abs(ring_area(hole)) for hole in holes)


def ring_area(ring: list) -> float:
    count = len(ring)
    if count < 3:
        return 0.0
    total = 0.0
    for index in range(count):
        lower = ring[index]
        middle = ring[(index + 1) % count]
        upper = ring[(index + 2) % count]
        total += (math.radians(upper[0]) - math.radians(lower[0])) * math.sin(math.radians(middle[1]))
    return total * EARTH_RADIUS_M * EARTH_RADIUS_M / 2
