# Allègement des objets envoyés au front par les couches vectorielles du catalogue (WFS, GeoJSON) :
# sommets plus proches qu'un pixel du zoom demandé retirés, propriétés réduites aux valeurs simples.
# Fonctions pures, sans réseau ni base.

from typing import Any

# Largeur d'une tuile du front, en pixels : sert à calculer la taille d'un pixel à un zoom donné.
TILE_SIZE_PX = 256
# Au-delà, une chaîne de caractères est coupée : une propriété n'a pas à peser plus qu'une étiquette.
MAX_TEXT_LENGTH = 500
COORDINATE_DECIMALS = 6

Bbox = tuple[float, float, float, float]


# Taille d'un pixel en degrés de longitude au zoom donné : en deçà, deux sommets se confondent à l'écran.
def pixel_degrees(zoom: int) -> float:
    return 360 / (TILE_SIZE_PX * 2**zoom)


def _rounded(position: list[float]) -> list[float]:
    return [round(value, COORDINATE_DECIMALS) for value in position[:2]]


def _far_enough(a: list[float], b: list[float], tolerance: float) -> bool:
    return abs(a[0] - b[0]) >= tolerance or abs(a[1] - b[1]) >= tolerance


# Sommets plus proches du précédent gardé qu'un pixel retirés, le dernier toujours gardé. Les sommets
# restants ne bougent pas : les ramener sur une grille dessinait des marches d'escalier le long des
# courbes denses (constaté le 26/10/2026 sur les contours Natura 2000).
def _thinned_line(positions: list[list[float]], tolerance: float) -> list[list[float]]:
    line: list[list[float]] = []
    for position in positions:
        if not line or _far_enough(line[-1], position, tolerance):
            line.append(_rounded(position))
    last = _rounded(positions[-1]) if positions else None
    if last is not None and line[-1] != last:
        if len(line) > 1 and not _far_enough(line[-1], last, tolerance):
            line[-1] = last
        else:
            line.append(last)
    return line


# Anneau de polygone : au moins 4 sommets (le premier répété à la fin), sinon il est trop petit pour être vu.
def _thinned_ring(ring: list[list[float]], tolerance: float) -> list[list[float]] | None:
    thinned = _thinned_line(ring, tolerance)
    if thinned and thinned[0] != thinned[-1]:
        thinned.append(thinned[0])
    return thinned if len(thinned) >= 4 else None


# Polygone : sans son contour extérieur, il disparaît ; un trou trop petit est seulement retiré.
def _thinned_polygon(rings: list[list[list[float]]], tolerance: float) -> list[list[list[float]]] | None:
    if not rings:
        return None
    outer = _thinned_ring(rings[0], tolerance)
    if outer is None:
        return None
    holes = [hole for hole in (_thinned_ring(ring, tolerance) for ring in rings[1:]) if hole is not None]
    return [outer, *holes]


# Géométrie GeoJSON allégée, ou None si plus rien n'est visible au zoom demandé.
def simplify(geometry: dict[str, Any] | None, zoom: int) -> dict[str, Any] | None:
    if not geometry:
        return None
    tolerance = pixel_degrees(zoom)
    kind, coordinates = geometry.get("type"), geometry.get("coordinates")
    if kind == "Point":
        return {"type": kind, "coordinates": _rounded(coordinates)}
    if kind == "MultiPoint":
        return {"type": kind, "coordinates": [_rounded(position) for position in coordinates]}
    if kind == "LineString":
        line = _thinned_line(coordinates, tolerance)
        return {"type": kind, "coordinates": line} if len(line) >= 2 else None
    if kind == "MultiLineString":
        lines = [line for line in (_thinned_line(part, tolerance) for part in coordinates) if len(line) >= 2]
        return {"type": kind, "coordinates": lines} if lines else None
    if kind == "Polygon":
        polygon = _thinned_polygon(coordinates, tolerance)
        return {"type": kind, "coordinates": polygon} if polygon else None
    if kind == "MultiPolygon":
        polygons = [polygon for polygon in (_thinned_polygon(part, tolerance) for part in coordinates) if polygon]
        return {"type": kind, "coordinates": polygons} if polygons else None
    return None


# Anneau découpé à l'emprise demandée (algorithme de Sutherland-Hodgman, un bord du rectangle après
# l'autre). Certains polygones (CORINE Land Cover) couvrent des centaines de km² avec des milliers de
# sommets : sans découpage, un écran au zoom 13 dépasse 5 Mo.
def _clipped_ring(ring: list[list[float]], bbox: Bbox) -> list[list[float]]:
    west, south, east, north = bbox
    edges = (
        (lambda p: p[0] >= west, lambda a, b: _at_x(a, b, west)),
        (lambda p: p[0] <= east, lambda a, b: _at_x(a, b, east)),
        (lambda p: p[1] >= south, lambda a, b: _at_y(a, b, south)),
        (lambda p: p[1] <= north, lambda a, b: _at_y(a, b, north)),
    )
    points = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    for inside, crossing in edges:
        if not points:
            break
        kept: list[list[float]] = []
        for index, current in enumerate(points):
            previous = points[index - 1]
            if inside(current):
                if not inside(previous):
                    kept.append(crossing(previous, current))
                kept.append(current)
            elif inside(previous):
                kept.append(crossing(previous, current))
        points = kept
    return [*points, points[0]] if points else []


def _at_x(a: list[float], b: list[float], x: float) -> list[float]:
    return [x, a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0])]


def _at_y(a: list[float], b: list[float], y: float) -> list[float]:
    return [a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]), y]


def _clipped_polygon(rings: list[list[list[float]]], bbox: Bbox) -> list[list[list[float]]]:
    clipped = [_clipped_ring(ring, bbox) for ring in rings]
    if not clipped or not clipped[0]:
        return []
    return [clipped[0], *(ring for ring in clipped[1:] if ring)]


# Surfaces découpées à l'emprise ; points et lignes inchangés (le service les a déjà filtrés).
def clip(geometry: dict[str, Any] | None, bbox: Bbox) -> dict[str, Any] | None:
    if not geometry:
        return None
    kind, coordinates = geometry.get("type"), geometry.get("coordinates")
    if kind == "Polygon":
        polygon = _clipped_polygon(coordinates, bbox)
        return {"type": kind, "coordinates": polygon} if polygon else None
    if kind == "MultiPolygon":
        polygons = [polygon for polygon in (_clipped_polygon(part, bbox) for part in coordinates) if polygon]
        return {"type": kind, "coordinates": polygons} if polygons else None
    return geometry


# Seules les valeurs simples passent : les listes et objets imbriqués (fréquents dans Hub'Eau) ne
# s'affichent pas et alourdissent la réponse.
def plain_properties(properties: dict[str, Any] | None) -> dict[str, Any]:
    plain: dict[str, Any] = {}
    for key, value in (properties or {}).items():
        if isinstance(value, str):
            plain[key] = value[:MAX_TEXT_LENGTH]
        elif value is None or isinstance(value, (bool, int, float)):
            plain[key] = value
    return plain


# Objets prêts pour la carte : surfaces découpées à l'emprise, géométrie allégée, propriétés simples ;
# ceux qui sortent de l'emprise ou disparaissent au zoom demandé sont retirés.
def light_features(features: list[dict[str, Any]], bbox: Bbox, zoom: int) -> list[dict[str, Any]]:
    light = []
    for feature in features:
        geometry = simplify(clip(feature.get("geometry"), bbox), zoom)
        if geometry is not None:
            light.append({"type": "Feature", "geometry": geometry, "properties": plain_properties(feature.get("properties"))})
    return light


# Inverse latitude et longitude de chaque position : certains serveurs WFS (MapServer en WFS 1.1.0
# et EPSG:4326) les donnent dans l'ordre latitude, longitude.
def swap_axes(geometry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not geometry:
        return geometry

    def swap(value: Any) -> Any:
        if value and isinstance(value[0], (int, float)):
            return [value[1], value[0], *value[2:]]
        return [swap(part) for part in value]

    return {**geometry, "coordinates": swap(geometry["coordinates"])}
