# Logique métier du cadastre : appelé par routes.py, appelle sources.py, puis calcule la surface.

import math

from app.domains.france.land_registry import sources
from app.domains.france.land_registry.entities import Parcel, ParcelReference

# Rayon équatorial de la Terre (ellipsoïde WGS84), en mètres.
EARTH_RADIUS_M = 6378137.0


# Renvoie la parcelle correspondant à la référence, ou None si l'IGN n'en trouve aucune.
def find_parcel(reference: ParcelReference) -> Parcel | None:
    features = sources.parcel_features(reference)
    # Une référence complète désigne une seule parcelle : on garde la première.
    return to_parcel(features[0]) if features else None


# Transforme une « feature » GeoJSON de l'IGN en entité Parcel.
# Les valeurs absentes deviennent des chaînes vides ou None plutôt que de lever une erreur.
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
        # Surface calculée à partir du contour, arrondie au dixième de m².
        computed_area_m2=round(geodesic_area_m2(geometry), 1),
        geometry=geometry,
    )


# Surface en m² d'un Polygon ou d'un MultiPolygon GeoJSON (coordonnées en degrés).
def geodesic_area_m2(geometry: dict) -> float:
    coordinates = geometry.get("coordinates") or []
    # Un MultiPolygon est une liste de polygones ; un Polygon est traité comme une liste d'un seul.
    polygons = coordinates if geometry.get("type") == "MultiPolygon" else [coordinates]
    return sum(polygon_area(polygon) for polygon in polygons)


# Surface d'un polygone : son contour extérieur moins ses trous éventuels.
def polygon_area(rings: list) -> float:
    if not rings:
        return 0.0
    # Le premier anneau est le contour extérieur, les suivants sont les trous.
    outer, *holes = rings
    # abs() : le signe dépend du sens de parcours de l'anneau, qu'on ignore.
    return abs(ring_area(outer)) - sum(abs(ring_area(hole)) for hole in holes)


# Surface d'un anneau sur une sphère (méthode de Chamberlain et Duquette, la même que Turf.js
# ou OpenLayers). Le résultat est signé selon le sens de parcours.
def ring_area(ring: list) -> float:
    count = len(ring)
    # Moins de 3 points : pas de surface.
    if count < 3:
        return 0.0
    total = 0.0
    # Pour chaque point, on prend le précédent et le suivant (le modulo fait boucler en fin d'anneau).
    for index in range(count):
        lower = ring[index]
        middle = ring[(index + 1) % count]
        upper = ring[(index + 2) % count]
        # Écart de longitude des voisins × sinus de la latitude du point du milieu (en radians).
        total += (math.radians(upper[0]) - math.radians(lower[0])) * math.sin(math.radians(middle[1]))
    # Conversion de la somme en m² sur la sphère de rayon EARTH_RADIUS_M.
    return total * EARTH_RADIUS_M * EARTH_RADIUS_M / 2
