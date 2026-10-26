# Catalogue des couches de la carte, commun à tous les agents (ADR-0043 du front) : catégories et
# couches activées de tous les pays, le front ne garde que celles du pays affiché.

from decimal import Decimal
from typing import Any

from app.database.connection import refonte_transaction
from app.domains.layer_catalog import queries, sources
from app.domains.layer_catalog.geometry import Bbox, light_features


def _zoom(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _localized(french: str | None, english: str | None) -> dict[str, str | None] | None:
    return None if french is None else {"fr": french, "en": english}


def _layer_json(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": row["code"],
        "category": row["category"],
        "country": row["country"],
        "label": _localized(row["label_fr"], row["label_en"]),
        "description": _localized(row["description_fr"], row["description_en"]),
        "kind": row["kind"],
        "url": row["url"],
        "params": row["params"],
        "attribution": row["attribution"],
        "legendUrl": row["legend_url"],
        "minZoom": _zoom(row["min_zoom"]),
        "maxZoom": _zoom(row["max_zoom"]),
        "renderer": row["renderer"],
    }


def catalog() -> dict[str, Any]:
    with refonte_transaction() as connection:
        categories = queries.categories(connection)
        layers = queries.enabled_layers(connection)

    return {
        "categories": [{"code": row["code"], "label": _localized(row["label_fr"], row["label_en"])} for row in categories],
        "layers": [_layer_json(row) for row in layers],
    }


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

    fetch = sources.wfs_features if layer["kind"] == "wfs" else sources.geojson_features
    found = fetch(layer["url"], layer["params"] or {}, bbox)
    return {
        "type": "FeatureCollection",
        "features": light_features(found, bbox, zoom),
        "truncated": len(found) >= sources.MAX_FEATURES,
    }
