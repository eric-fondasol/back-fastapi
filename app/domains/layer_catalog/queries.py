# Lecture du catalogue des couches (tables layer_categories et catalog_layers, migration 0007) et des
# couches stockées en base (catalog_layer_features, catalog_layer_tiles, catalog_layer_legends, migration 0038).

from typing import Any

from sqlalchemy import Connection, text


# Catégories rangées comme dans le panneau, avec le code de leur catégorie parente (parent_id, migrations 0019
# et 0039) : une sous-catégorie suit l'ordre des positions parmi les catégories de même parent.
def categories(connection: Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            """
            SELECT c.code, c.label_fr, c.label_en, p.code AS parent
            FROM layer_categories c
            LEFT JOIN layer_categories p ON p.id = c.parent_id
            ORDER BY c.position, c.code
            """
        )
    )
    return [dict(row) for row in rows.mappings()]


# Couches activées seulement, rangées comme dans le panneau : catégorie, puis ordre dans la catégorie.
def enabled_layers(connection: Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            """
            SELECT l.code, c.code AS category, l.country, l.label_fr, l.label_en, l.description_fr, l.description_en,
                   l.kind, l.url, l.params, l.attribution, l.legend_url, l.min_zoom, l.max_zoom, l.renderer,
                   EXISTS (SELECT 1 FROM catalog_layer_legends g WHERE g.layer_id = l.id) AS stored_legend
            FROM catalog_layers l
            JOIN layer_categories c ON c.id = l.category_id
            WHERE l.enabled
            ORDER BY c.position, c.code, l.position, l.code
            """
        )
    )
    return [dict(row) for row in rows.mappings()]


# Couche vectorielle activée (WFS, GeoJSON ou objets en base) : de quoi interroger son service ou sa table.
# None si le code est inconnu, désactivé, ou désigne une couche d'images.
def feature_layer(connection: Connection, code: str) -> dict[str, Any] | None:
    row = connection.execute(
        text(
            """
            SELECT id, code, kind, url, params, min_zoom, max_zoom
            FROM catalog_layers
            WHERE code = :code AND enabled AND kind IN ('wfs', 'geojson', 'database')
            """
        ),
        {"code": code},
    ).mappings().first()
    return None if row is None else dict(row)


# Couche activée dont le back sert les tuiles : WMTS ou WMS relayée (params.relayed, migrations 0010 et
# 0036), tuiles stockées en base (database-tiles, migration 0038) ou ouvrages BSS (bss, migration 0047). None sinon.
def relayed_tile_layer(connection: Connection, code: str) -> dict[str, Any] | None:
    row = connection.execute(
        text(
            """
            SELECT id, code, kind, url, params, min_zoom
            FROM catalog_layers
            WHERE code = :code AND enabled
              AND (kind IN ('database-tiles', 'bss') OR (kind IN ('wmts', 'wms') AND (params ->> 'relayed')::boolean IS TRUE))
            """
        ),
        {"code": code},
    ).mappings().first()
    return None if row is None else dict(row)


# Objets d'une couche en base qui touchent l'emprise, découpés à l'emprise et simplifiés à la tolérance donnée
# (en degrés) par PostGIS : une aire de protection peut compter des dizaines de milliers de sommets, inutile de
# les sortir de la base. Au plus « limit » objets.
def stored_features(connection: Connection, layer_id: Any, bbox: tuple[float, float, float, float], tolerance: float, limit: int) -> list[dict[str, Any]]:
    west, south, east, north = bbox
    rows = connection.execute(
        text(
            """
            SELECT geometry, properties FROM (
                SELECT ST_AsGeoJSON(ST_SimplifyPreserveTopology(ST_ClipByBox2D(f.geometry, envelope.box), :tolerance), 6)::json
                           AS geometry,
                       f.properties
                FROM catalog_layer_features f,
                     (SELECT ST_MakeEnvelope(:west, :south, :east, :north, 4326) AS box) envelope
                WHERE f.layer_id = :layer_id AND f.geometry && envelope.box
                LIMIT :limit
            ) clipped
            WHERE geometry IS NOT NULL
            """
        ),
        {"layer_id": layer_id, "west": west, "south": south, "east": east, "north": north, "tolerance": tolerance, "limit": limit},
    ).mappings()
    return [{"type": "Feature", "geometry": row["geometry"], "properties": row["properties"]} for row in rows]


# Tuile stockée d'une couche database-tiles : (image, type), ou None hors de la zone couverte.
def stored_tile(connection: Connection, layer_id: Any, z: int, x: int, y: int) -> tuple[bytes, str] | None:
    row = connection.execute(
        text("SELECT content, content_type FROM catalog_layer_tiles WHERE layer_id = :layer_id AND z = :z AND x = :x AND y = :y"),
        {"layer_id": layer_id, "z": z, "x": x, "y": y},
    ).first()
    return None if row is None else (bytes(row.content), row.content_type)


# Légende stockée d'une couche activée : (image, type), ou None.
def stored_legend(connection: Connection, code: str) -> tuple[bytes, str] | None:
    row = connection.execute(
        text(
            """
            SELECT g.content, g.content_type
            FROM catalog_layer_legends g
            JOIN catalog_layers l ON l.id = g.layer_id
            WHERE l.code = :code AND l.enabled
            """
        ),
        {"code": code},
    ).first()
    return None if row is None else (bytes(row.content), row.content_type)


MVT_EXTENT = 4096
MVT_BUFFER = 64


# Tuile vectorielle (MVT, couche « features ») des ouvrages BSS (table bss_wells, migration 0047) : ID_BSS,
# url_fiche, code_log (classe de la légende) et les champs de la fiche au survol (côte du sol, profondeur atteinte,
# niveau d'eau et sa date) ; b"" si aucun ouvrage ne touche la tuile. Les autres colonnes restent en base.
def bss_tile(connection: Connection, z: int, x: int, y: int) -> bytes:
    tile = connection.execute(
        text(
            f"""
            WITH bounds AS (
                SELECT ST_TileEnvelope(:z, :x, :y) AS box,
                       ST_TileEnvelope(:z, :x, :y, margin => {MVT_BUFFER / MVT_EXTENT}) AS wide
            )
            SELECT ST_AsMVT(tile, 'features', {MVT_EXTENT}, 'geom')
            FROM (
                SELECT ST_AsMVTGeom(w.geometry, bounds.box, {MVT_EXTENT}, {MVT_BUFFER}, true) AS geom,
                       w.bss_id AS "ID_BSS", w.sheet_url AS url_fiche, w.code_log,
                       w.z_bdalti, w.prof_atteinte, w.prof_eau_sol, w.date_eau_sol
                FROM bss_wells w, bounds
                WHERE w.geometry && bounds.wide
            ) tile
            WHERE geom IS NOT NULL
            """
        ),
        {"z": z, "x": x, "y": y},
    ).scalar_one()
    return bytes(tile or b"")
