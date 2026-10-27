# Objets métier du cadastre du Québec, manipulés par services.py. Ce ne sont pas des modèles de tables.

import math
from dataclasses import dataclass

# Rayon équatorial de l'ellipsoïde WGS 84, en mètres, pris comme rayon de la sphère pour le calcul de surface.
EARTH_RADIUS_M = 6378137.0


# Lot du cadastre rénové du Québec, tel que publié par le « Cadastre allégé » (numéro et contour seulement).
@dataclass(frozen=True)
class Lot:
    # Numéro de lot, au format du cadastre : chiffres groupés par trois (ex. « 4 019 828 »).
    number: str
    # Contour du lot en GeoJSON (Polygon ou MultiPolygon, coordonnées longitude/latitude).
    geometry: dict

    # Superficie calculée à partir du contour, en m², arrondie au centième. Le service ne publie pas la
    # superficie officielle : c'est une estimation, juste à quelques millièmes près pour un lot.
    def area_m2(self) -> float:
        polygons = [self.geometry["coordinates"]] if self.geometry["type"] == "Polygon" else self.geometry["coordinates"]
        total = 0.0
        for rings in polygons:
            outer, *holes = rings
            total += _ring_area_m2(outer) - sum(_ring_area_m2(hole) for hole in holes)
        return round(total, 2)


# Aire d'un anneau sur la sphère (méthode de Chamberlain et Duquette, celle de Turf.js), en m².
def _ring_area_m2(ring: list[list[float]]) -> float:
    total = 0.0
    for start, end in zip(ring, ring[1:] + ring[:1]):
        total += math.radians(end[0] - start[0]) * (2 + math.sin(math.radians(start[1])) + math.sin(math.radians(end[1])))
    return abs(total * EARTH_RADIUS_M**2 / 2)
