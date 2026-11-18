# Catalogue des couches de la carte, commun à tous les agents (ADR-0043 du front) : catégories et
# couches activées de tous les pays, le front ne garde que celles du pays affiché.

from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from app.core.config import config
from app.database.connection import refonte_transaction
from app.domains.layer_catalog import queries, sources
from app.domains.layer_catalog.geometry import Bbox, light_features, pixel_degrees


def _zoom(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _localized(french: str | None, english: str | None) -> dict[str, str | None] | None:
    return None if french is None else {"fr": french, "en": english}


CLASS_PROPERTY = "classe"
CLASS_TABLES = {"wetlands": "quebec_wetland_classes", "potential-wetlands": "quebec_potential_wetland_classes"}

Classes = dict[str, list[dict[str, Any]]]


# Les classes des couches de milieux humides sont dans leur table (CLASS_TABLES), et non dans params : le front
# les reçoit comme celles de la BSS, dans params.classes.
def _params(row: dict[str, Any], classes: Classes) -> dict[str, Any] | None:
    values = classes.get(row["kind"])
    if not values:
        return row["params"]
    return {**(row["params"] or {}), "classes": {"property": CLASS_PROPERTY, "values": values}}


def _layer_json(row: dict[str, Any], classes: Classes) -> dict[str, Any]:
    return {
        "code": row["code"],
        "category": row["category"],
        "country": row["country"],
        "label": _localized(row["label_fr"], row["label_en"]),
        "description": _localized(row["description_fr"], row["description_en"]),
        "kind": row["kind"],
        "url": row["url"],
        "params": _params(row, classes),
        "attribution": row["attribution"],
        "legendUrl": row["legend_url"],
        "minZoom": _zoom(row["min_zoom"]),
        "maxZoom": _zoom(row["max_zoom"]),
        "renderer": row["renderer"],
        "storedLegend": row["stored_legend"],
    }


def _relayed(row: dict[str, Any]) -> bool:
    return (row["params"] or {}).get("relayed") is True


def _private_api_key() -> str | None:
    key = config.ign_private_api_key
    return key.get_secret_value() if key is not None and key.get_secret_value() else None


def _needs_private_key(row: dict[str, Any]) -> bool:
    return _relayed(row) and row["kind"] == "wmts"


# Une couche WMTS relayée (tuiles demandées au back, qui ajoute la clé) n'est proposée que si la clé est
# configurée : sans elle, ses tuiles seraient toutes en 404. Une couche WMS relayée ne l'est que parce
# que son service n'autorise pas le navigateur à lire ses images (pas d'en-tête CORS) : aucune clé.
def catalog() -> dict[str, Any]:
    with refonte_transaction() as connection:
        categories = queries.categories(connection)
        layers = queries.enabled_layers(connection)
        classes = {kind: queries.layer_classes(connection, table) for kind, table in CLASS_TABLES.items()}

    has_key = _private_api_key() is not None
    return {
        "categories": [
            {"code": row["code"], "label": _localized(row["label_fr"], row["label_en"]), "parent": row["parent"]} for row in categories
        ],
        "layers": [_layer_json(row, classes) for row in layers if has_key or not _needs_private_key(row)],
    }


class UnknownTileLayer(Exception):
    pass


MVT_MEDIA_TYPE = "application/vnd.mapbox-vector-tile"


# En deçà du zoom minimal de la couche, la tuile est vide sans interroger la table : près d'un million de points.
def _bss_tile(connection: Connection, layer: dict[str, Any], z: int, x: int, y: int) -> bytes:
    min_zoom = _zoom(layer["min_zoom"])
    return b"" if min_zoom is not None and z < min_zoom else queries.bss_tile(connection, z, x, y)


CASIAS_SHAPES = {"fr-georisques-casias-points": "point", "fr-georisques-casias-polygones": "polygon"}


# En deçà du zoom minimal de la couche, ou pour une couche casias qui n'est ni les points ni les emprises, la tuile
# est vide sans interroger la table.
def _casias_tile(connection: Connection, layer: dict[str, Any], z: int, x: int, y: int) -> bytes:
    min_zoom = _zoom(layer["min_zoom"])
    shape = CASIAS_SHAPES.get(layer["code"])
    return b"" if shape is None or (min_zoom is not None and z < min_zoom) else queries.casias_tile(connection, shape, z, x, y)


POLYGON_TILES = {"wetlands": queries.wetlands_tile, "potential-wetlands": queries.potential_wetlands_tile}


# En deçà du zoom minimal de la couche, la tuile est vide sans interroger la table : de 300 000 à 2,4 millions de
# polygones.
def _polygon_tile(connection: Connection, layer: dict[str, Any], z: int, x: int, y: int) -> bytes:
    min_zoom = _zoom(layer["min_zoom"])
    return b"" if min_zoom is not None and z < min_zoom else POLYGON_TILES[layer["kind"]](connection, z, x, y)


# Tuile d'une couche servie par le back : lue en base (database-tiles, ou tuile vectorielle des ouvrages BSS, des sites CASIAS ou des milieux humides du Québec, détaillés ou potentiels), WMTS demandée au service privé avec
# la clé, WMS demandée telle quelle. UnknownTileLayer si le code ne désigne pas une telle couche activée, ou
# si la clé qu'il faut à une couche WMTS n'est pas configurée ; TileNotFound hors de la zone couverte.
def tile(code: str, z: int, x: int, y: int) -> tuple[bytes, str]:
    with refonte_transaction() as connection:
        layer = queries.relayed_tile_layer(connection, code)
        stored = None if layer is None or layer["kind"] != "database-tiles" else queries.stored_tile(connection, layer["id"], z, x, y)
        wells = None if layer is None or layer["kind"] != "bss" else _bss_tile(connection, layer, z, x, y)
        sites = None if layer is None or layer["kind"] != "casias" else _casias_tile(connection, layer, z, x, y)
        polygons = None if layer is None or layer["kind"] not in POLYGON_TILES else _polygon_tile(connection, layer, z, x, y)
    if layer is None:
        raise UnknownTileLayer(code)
    if wells is not None:
        return wells, MVT_MEDIA_TYPE
    if sites is not None:
        return sites, MVT_MEDIA_TYPE
    if polygons is not None:
        return polygons, MVT_MEDIA_TYPE
    if layer["kind"] == "database-tiles":
        if stored is None:
            raise sources.TileNotFound()
        return stored
    if layer["kind"] == "wms":
        return sources.wms_tile(layer["url"], layer["params"], z, x, y)
    api_key = _private_api_key()
    if api_key is None:
        raise UnknownTileLayer(code)
    return sources.wmts_tile(layer["url"], layer["params"], api_key, z, x, y)


class UnknownFeatureLayer(Exception):
    pass


# Objets d'une couche vectorielle du catalogue dans l'emprise demandée, allégés pour le zoom du front.
# En deçà du zoom minimal de la couche, rien n'est demandé au service : le front ne l'affiche pas.
# truncated signale qu'il y avait davantage d'objets que le plafond (sources.MAX_FEATURES).
def feature_collection(code: str, bbox: Bbox, zoom: int) -> dict[str, Any]:
    with refonte_transaction() as connection:
        layer = queries.feature_layer(connection, code)
    if layer is None:
        raise UnknownFeatureLayer(code)

    min_zoom = _zoom(layer["min_zoom"])
    if min_zoom is not None and zoom < min_zoom:
        return {"type": "FeatureCollection", "features": [], "truncated": False}

    if layer["kind"] == "database":
        with refonte_transaction() as connection:
            found = queries.stored_features(connection, layer["id"], bbox, pixel_degrees(zoom), sources.MAX_FEATURES)
    else:
        fetch = sources.wfs_features if layer["kind"] == "wfs" else sources.geojson_features
        found = fetch(layer["url"], layer["params"] or {}, bbox)
    return {
        "type": "FeatureCollection",
        "features": light_features(found, bbox, zoom),
        "truncated": len(found) >= sources.MAX_FEATURES,
    }


class UnknownLegend(Exception):
    pass


# Image de légende stockée en base d'une couche activée (catalog_layer_legends). UnknownLegend sinon.
def legend(code: str) -> tuple[bytes, str]:
    with refonte_transaction() as connection:
        stored = queries.stored_legend(connection, code)
    if stored is None:
        raise UnknownLegend(code)
    return stored
