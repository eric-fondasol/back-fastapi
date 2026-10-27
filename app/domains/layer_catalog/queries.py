# Lecture du catalogue des couches (tables layer_categories et catalog_layers, migration 0007).

from typing import Any

from sqlalchemy import Connection, text


def categories(connection: Connection) -> list[dict[str, Any]]:
    rows = connection.execute(text("SELECT code, label_fr, label_en FROM layer_categories ORDER BY position, code"))
    return [dict(row) for row in rows.mappings()]


# Couches activées seulement, rangées comme dans le panneau : catégorie, puis ordre dans la catégorie.
def enabled_layers(connection: Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            """
            SELECT l.code, c.code AS category, l.country, l.label_fr, l.label_en, l.description_fr, l.description_en,
                   l.kind, l.url, l.params, l.attribution, l.legend_url, l.min_zoom, l.max_zoom, l.renderer
            FROM catalog_layers l
            JOIN layer_categories c ON c.id = l.category_id
            WHERE l.enabled
            ORDER BY c.position, c.code, l.position, l.code
            """
        )
    )
    return [dict(row) for row in rows.mappings()]


# Couche vectorielle activée (WFS ou GeoJSON) : de quoi interroger son service. None si le code est
# inconnu, désactivé, ou désigne une couche d'images (servie directement au navigateur).
def feature_layer(connection: Connection, code: str) -> dict[str, Any] | None:
    row = connection.execute(
        text(
            """
            SELECT code, kind, url, params, min_zoom, max_zoom
            FROM catalog_layers
            WHERE code = :code AND enabled AND kind IN ('wfs', 'geojson')
            """
        ),
        {"code": code},
    ).mappings().first()
    return None if row is None else dict(row)


# Couche WMTS activée dont le back relaie les tuiles (params.relayed, migration 0010). None sinon.
def relayed_tile_layer(connection: Connection, code: str) -> dict[str, Any] | None:
    row = connection.execute(
        text(
            """
            SELECT code, url, params
            FROM catalog_layers
            WHERE code = :code AND enabled AND kind = 'wmts' AND (params ->> 'relayed')::boolean IS TRUE
            """
        ),
        {"code": code},
    ).mappings().first()
    return None if row is None else dict(row)
