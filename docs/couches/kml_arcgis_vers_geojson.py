# KML exporté d'ArcGIS vers GeoJSON (docs/couches/couches-en-base.md) : attributs lus dans le tableau HTML de
# la description de chaque Placemark, nom du Placemark gardé dans CODE. Bibliothèque standard seulement.
#
#   python3 -I kml_arcgis_vers_geojson.py doc.kml sortie.geojson [champ ignoré …]

import json
import re
import sys
import xml.etree.ElementTree as ET

KML = "{http://www.opengis.net/kml/2.2}"
ARCGIS_FIELDS = {"FID", "AREA", "PERIMETER", "GEO_", "GEO_ID", "GEO_TYPE", "GEO_SYM", "GEO_PAT", "GEO_MISC", "GEO_LINK", "Id"}


def positions(text):
    return [[round(float(value), 6) for value in point.split(",")[:2]] for point in text.split()]


def attributes(description, ignored):
    cells = re.findall(r"<td>([^<]*)</td>\s*<td>([^<]*)</td>", description or "")
    return {key: value for key, value in cells if key not in ignored}


def geometry(placemark):
    polygons = [
        [positions(polygon.find(f"{KML}outerBoundaryIs/{KML}LinearRing/{KML}coordinates").text)]
        + [positions(ring.text) for ring in polygon.findall(f"{KML}innerBoundaryIs/{KML}LinearRing/{KML}coordinates")]
        for polygon in placemark.iter(f"{KML}Polygon")
    ]
    if polygons:
        return {"type": "MultiPolygon", "coordinates": polygons}
    return {"type": "MultiLineString", "coordinates": [positions(line.find(f"{KML}coordinates").text) for line in placemark.iter(f"{KML}LineString")]}


def main(source, target, ignored):
    text = re.sub(r' xsi:schemaLocation="[^"]*"', "", open(source, encoding="utf-8").read())
    features = []
    for placemark in ET.fromstring(text).iter(f"{KML}Placemark"):
        properties = {"CODE": placemark.findtext(f"{KML}name", default="")}
        properties.update(attributes(placemark.findtext(f"{KML}description", default=""), ignored))
        features.append({"type": "Feature", "properties": properties, "geometry": geometry(placemark)})
    with open(target, "w", encoding="utf-8") as output:
        json.dump({"type": "FeatureCollection", "features": features}, output, ensure_ascii=False)
    print(f"{len(features)} objets écrits dans {target}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], ARCGIS_FIELDS | set(sys.argv[3:]))
