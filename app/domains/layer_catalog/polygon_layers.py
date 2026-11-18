# Import commun des couches de polygones en base, lues dans un GeoPackage : milieux humides du Québec (wetlands.py,
# migration 0049) et milieux humides potentiels (potential_wetlands.py, migration 0050). Chaque couche décrit sa
# table, la table du fichier, sa clé, la projection du fichier et la table de ses classes (PolygonLayer).
#
# Comme pour CASIAS et BASOL (site_layers.py), le GeoPackage est lu avec sqlite3 et sa géométrie confiée à
# PostGIS une fois l'en-tête retiré. Les colonnes du fichier sont rapprochées de celles de la table sans tenir compte de la casse
# (exports ArcGIS en majuscules). Toute géométrie passe par ST_CurveToLine : les fichiers ont des MULTISURFACE,
# que ST_HasArc ne repère pas quand elles sont faites de polygones simples.
#
# L'import remplace toute la table en une transaction. Il la vide par TRUNCATE et non DELETE (qui laissait les
# anciennes lignes mortes et doublait la taille de la table à chaque réimport), et reconstruit l'index spatial
# après le chargement, plus rapide que de le tenir à jour ligne à ligne : la table est verrouillée jusqu'à la fin
# de l'import, les tuiles de la couche attendent. À lancer hors des heures d'usage pour un gros fichier.

import argparse
import sqlite3
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection, text

from app.database.connection import refonte_transaction
from app.domains.layer_catalog.site_layers import MAX_MERCATOR_LATITUDE, ImportRefused, wkb_of

GEOMETRY = "geom"
COMPUTED = ("geometry",)
IMPORT_TABLE = "polygons_import"


@dataclass(frozen=True)
class PolygonLayer:
    table: str
    source_table: str
    key: str
    srid: int
    class_column: str
    class_table: str
    label: str

    @property
    def geometry_index(self) -> str:
        return f"{self.table}_geometry"


def _text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


@dataclass(frozen=True)
class Polygon:
    values: tuple[str | None, ...]
    wkb: bytes


@dataclass(frozen=True)
class SourceFile:
    path: Path
    columns: tuple[str, ...]
    names: tuple[str, ...]
    ignored: tuple[str, ...]
    missing: tuple[str, ...]


def table_columns(connection: Connection, layer: PolygonLayer) -> tuple[str, ...]:
    rows = connection.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = :table ORDER BY ordinal_position"),
        {"table": layer.table},
    ).scalars()
    return tuple(column for column in rows if column not in COMPUTED)


def _connect(path: Path) -> sqlite3.Connection:
    database = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    database.row_factory = sqlite3.Row
    return database


def open_source(path: Path, wanted: tuple[str, ...], layer: PolygonLayer) -> SourceFile:
    if not path.is_file():
        raise ImportRefused(f"Fichier introuvable : {path}")
    database = _connect(path)
    try:
        found = {row["name"].lower(): row["name"] for row in database.execute(f'PRAGMA table_info("{layer.source_table}")')}
    finally:
        database.close()
    absent = [column for column in (layer.key, GEOMETRY) if column not in found]
    if absent:
        raise ImportRefused(f"Table {layer.source_table} absente ou sans les colonnes {', '.join(absent)}")
    columns = tuple(column for column in wanted if column in found)
    return SourceFile(
        path=path,
        columns=columns,
        names=tuple(found[column] for column in columns),
        ignored=tuple(name for column, name in found.items() if column not in wanted and column not in ("fid", GEOMETRY)),
        missing=tuple(column for column in wanted if column not in found),
    )


def _polygon_of(row: sqlite3.Row, source: SourceFile, key_index: int) -> Polygon | None:
    wkb = wkb_of(row[GEOMETRY])
    values = tuple(_text(row[name]) for name in source.names)
    if wkb is None or values[key_index] is None:
        return None
    return Polygon(values, wkb)


def _polygons(source: SourceFile, layer: PolygonLayer) -> Iterator[Polygon | None]:
    key_index = source.columns.index(layer.key)
    database = _connect(source.path)
    try:
        selected = ", ".join(f'"{name}"' for name in (*source.names, GEOMETRY))
        for row in database.execute(f'SELECT {selected} FROM "{layer.source_table}"'):
            yield _polygon_of(row, source, key_index)
    finally:
        database.close()


def _unknown_classes(connection: Connection, layer: PolygonLayer) -> tuple[str, ...]:
    rows = connection.execute(
        text(
            f"""
            SELECT DISTINCT {layer.class_column} FROM {IMPORT_TABLE}
            WHERE {layer.class_column} IS NOT NULL AND {layer.class_column} NOT IN (SELECT code FROM {layer.class_table})
            ORDER BY {layer.class_column}
            """
        )
    ).scalars()
    return tuple(rows)


@dataclass(frozen=True)
class ImportResult:
    imported: int
    skipped: int
    unknown_classes: tuple[str, ...] = ()


# Le fichier passe par une table temporaire chargée par COPY, puis est recopié avec sa géométrie lue par PostGIS,
# courbes converties en polygones et passée de la projection du fichier en EPSG:3857 ; une clé en double garde la
# première ligne lue (ON CONFLICT plutôt qu'un tri de toute la table), une géométrie illisible, vide ou hors du Web
# Mercator est écartée (contrôle sur son emprise en EPSG:4326), comme un polygone d'une classe absente de la table
# des classes (la clé étrangère le refuserait, et l'import entier avec lui) : ces classes sont signalées. Les
# colonnes absentes du fichier restent vides.
def import_polygons(connection: Connection, source: SourceFile, layer: PolygonLayer) -> ImportResult:
    connection.execute(text(f"TRUNCATE {layer.table}"))
    connection.execute(text(f"DROP INDEX IF EXISTS {layer.geometry_index}"))
    quoted = ", ".join(f'"{column}"' for column in source.columns)
    connection.execute(
        text(
            f"""
            CREATE TEMPORARY TABLE {IMPORT_TABLE} (
                {", ".join(f'"{column}" text' for column in source.columns)}, import_wkb bytea
            ) ON COMMIT DROP
            """
        )
    )
    skipped = 0
    driver = connection.connection.driver_connection
    with driver.cursor() as cursor, cursor.copy(f"COPY {IMPORT_TABLE} ({quoted}, import_wkb) FROM STDIN") as copy:
        for polygon in _polygons(source, layer):
            if polygon is None:
                skipped += 1
                continue
            copy.write_row((*polygon.values, polygon.wkb))
    has_class = layer.class_column in source.columns
    known_class = (
        f"AND ({layer.class_column} IS NULL OR {layer.class_column} IN (SELECT code FROM {layer.class_table}))" if has_class else ""
    )
    imported = connection.execute(
        text(
            f"""
            INSERT INTO {layer.table} ({quoted}, geometry)
            SELECT {quoted}, ST_Transform(geometry, 3857)
            FROM (
                SELECT *, ST_Transform(ST_Envelope(geometry), 4326) AS bounds
                FROM (
                    SELECT *, ST_SetSRID(ST_Force2D(ST_CurveToLine(ST_GeomFromWKB(import_wkb))), :srid) AS geometry
                    FROM {IMPORT_TABLE}
                ) read
                WHERE NOT ST_IsEmpty(geometry)
            ) parsed
            WHERE ST_YMin(bounds) >= -:max AND ST_YMax(bounds) <= :max AND ST_XMin(bounds) >= -180 AND ST_XMax(bounds) <= 180
              {known_class}
            ON CONFLICT ({layer.key}) DO NOTHING
            """
        ),
        {"srid": layer.srid, "max": MAX_MERCATOR_LATITUDE},
    ).rowcount
    total = connection.execute(text(f"SELECT count(*) FROM {IMPORT_TABLE}")).scalar_one()
    unknown = _unknown_classes(connection, layer) if has_class else ()
    connection.execute(text(f"DROP TABLE {IMPORT_TABLE}"))
    connection.execute(text(f"CREATE INDEX {layer.geometry_index} ON {layer.table} USING gist (geometry)"))
    connection.execute(text(f"ANALYZE {layer.table}"))
    if imported == 0:
        raise ImportRefused(f"Aucun objet valide dans le fichier pour {layer.label}")
    return ImportResult(imported=imported, skipped=skipped + total - imported, unknown_classes=unknown)


def main(arguments: list[str], layer: PolygonLayer, program: str) -> int:
    parser = argparse.ArgumentParser(prog=program)
    parser.add_argument("path", type=Path)
    options = parser.parse_args(arguments)
    try:
        with refonte_transaction() as connection:
            source = open_source(options.path, table_columns(connection, layer), layer)
            result = import_polygons(connection, source, layer)
    except ImportRefused as error:
        print(f"Import refusé : {error}", file=sys.stderr)
        return 1
    print(f"{layer.label} : {result.imported} importés, {result.skipped} écartés (géométrie ou clé manquante, ou clé en double)")
    if result.unknown_classes:
        print(f"Classes absentes de {layer.class_table}, objets écartés : {', '.join(result.unknown_classes)}")
    if source.missing:
        print(f"Colonnes absentes du fichier, laissées vides : {', '.join(source.missing)}")
    if source.ignored:
        print(f"Colonnes du fichier inconnues de la table, ignorées : {', '.join(source.ignored)}")
    return 0
