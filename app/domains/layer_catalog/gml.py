# Lecture d'une réponse WFS en GML (versions 2 et 3) : objets convertis en GeoJSON. Fonctions pures.
# Les coordonnées sont rendues dans l'ordre du serveur ; geometry.swap_axes les remet en longitude,
# latitude si besoin.

import xml.etree.ElementTree as ElementTree
from typing import Any

GML_NAMESPACES = ("http://www.opengis.net/gml", "http://www.opengis.net/gml/3.2")
GEOMETRY_TAGS = {"Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon", "MultiSurface", "MultiCurve"}
# Éléments qui décrivent l'objet lui-même sans être une propriété métier.
SKIPPED_PROPERTIES = {"boundedBy", "msGeometry", "geometry", "the_geom"}


class GmlError(Exception):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _is_gml(element: ElementTree.Element, name: str) -> bool:
    return _local(element.tag) == name and _namespace(element.tag) in GML_NAMESPACES


# GML 2 : « x,y x,y » dans <gml:coordinates> ; GML 3 : « x y x y » dans <gml:posList> ou <gml:pos>.
def _positions(element: ElementTree.Element) -> list[list[float]]:
    for child in element.iter():
        text = (child.text or "").strip()
        if _is_gml(child, "coordinates"):
            return [[float(value) for value in pair.split(",")[:2]] for pair in text.split()]
        if _is_gml(child, "posList"):
            values = [float(value) for value in text.split()]
            return [values[index : index + 2] for index in range(0, len(values) - 1, 2)]
    positions = [[float(value) for value in (child.text or "").split()[:2]] for child in element.iter() if _is_gml(child, "pos")]
    if positions:
        return positions
    raise GmlError("Géométrie GML sans coordonnées")


def _rings(polygon: ElementTree.Element) -> list[list[list[float]]]:
    outer, inner = [], []
    for child in polygon:
        name = _local(child.tag)
        if name in ("outerBoundaryIs", "exterior"):
            outer.append(_positions(child))
        elif name in ("innerBoundaryIs", "interior"):
            inner.append(_positions(child))
    return outer + inner


def _members(element: ElementTree.Element, kind: str) -> list[ElementTree.Element]:
    return [child for child in element.iter() if child is not element and _is_gml(child, kind)]


def _geometry(element: ElementTree.Element) -> dict[str, Any]:
    name = _local(element.tag)
    if name == "Point":
        return {"type": "Point", "coordinates": _positions(element)[0]}
    if name == "LineString":
        return {"type": "LineString", "coordinates": _positions(element)}
    if name == "Polygon":
        return {"type": "Polygon", "coordinates": _rings(element)}
    if name == "MultiPoint":
        return {"type": "MultiPoint", "coordinates": [_positions(point)[0] for point in _members(element, "Point")]}
    if name in ("MultiLineString", "MultiCurve"):
        return {"type": "MultiLineString", "coordinates": [_positions(line) for line in _members(element, "LineString")]}
    return {"type": "MultiPolygon", "coordinates": [_rings(polygon) for polygon in _members(element, "Polygon")]}


def _feature(member: ElementTree.Element) -> dict[str, Any] | None:
    geometry, properties = None, {}
    for field in member:
        geometries = [child for child in field.iter() if _local(child.tag) in GEOMETRY_TAGS and _namespace(child.tag) in GML_NAMESPACES]
        if geometries:
            geometry = geometry or _geometry(geometries[0])
        elif _local(field.tag) not in SKIPPED_PROPERTIES and len(field) == 0:
            properties[_local(field.tag)] = (field.text or "").strip() or None
    return None if geometry is None else {"type": "Feature", "geometry": geometry, "properties": properties}


# Objets d'une FeatureCollection WFS (featureMember, featureMembers ou member selon la version).
def features(document: bytes) -> list[dict[str, Any]]:
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as error:
        raise GmlError(f"Réponse WFS illisible : {error}") from error
    if _local(root.tag) != "FeatureCollection":
        raise GmlError(f"Le serveur WFS a renvoyé {_local(root.tag)} au lieu d'une FeatureCollection")
    found = []
    for container in root:
        if _local(container.tag) not in ("featureMember", "featureMembers", "member"):
            continue
        for member in container:
            feature = _feature(member)
            if feature is not None:
                found.append(feature)
    return found
