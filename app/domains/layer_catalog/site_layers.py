# Import commun des couches de sites en base, lues dans un extrait GeoPackage de Géorisques à une table par forme
# (points, emprises) : sites CASIAS (casias.py, migration 0048), sites BASOL (basol.py, migration 0051), secteurs
# SIS (sis.py, migration 0052, emprises seules), établissements pollueurs (polluting_facilities.py, migration
# 0053, points seuls), servitudes SUP (sup.py, migration 0054, emprises seules) et installations classées
# (icpe.py, migration 0055, points seuls). Chaque couche décrit sa table, les tables du fichier par forme et la
# colonne qui identifie un site (SiteLayer : code_metier, sauf pour les établissements pollueurs et les ICPE, qui
# n'en ont pas).
#
# Le GeoPackage est lu avec sqlite3 (pas de GDAL dans l'image) ; la géométrie, un en-tête GeoPackage suivi de WKB,
# est confiée telle quelle à PostGIS une fois l'en-tête retiré. Les colonnes copiées sont celles de la table qui
# existent dans chaque table du fichier (même nom). L'import remplace en une transaction tous les sites : le
# relancer avec un nouvel extrait suffit.

import argparse
import sqlite3
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection, text

from app.database.connection import refonte_transaction

GEOMETRY = "geom"
COMPUTED = ("shape", "geometry")
IMPORT_TABLE = "sites_import"
SHAPE_NAMES = {"point": "points", "polygon": "emprises"}

# Octets d'enveloppe selon les bits 1 à 3 des drapeaux de l'en-tête GeoPackage (aucune, xy, xyz, xym, xyzm).
ENVELOPE_SIZES = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
GEOPACKAGE_HEADER = 8
EMPTY_GEOMETRY = 0b10000
# Latitude extrême du Web Mercator : au-delà, ST_Transform vers EPSG:3857 diverge.
MAX_MERCATOR_LATITUDE = 85.05112878


class ImportRefused(Exception):
    pass


@dataclass(frozen=True)
class SiteLayer:
    table: str
    shapes: dict[str, str]
    label: str
    key: str = "code_metier"


def wkb_of(blob: bytes | None) -> bytes | None:
    if blob is None or len(blob) < GEOPACKAGE_HEADER or blob[:2] != b"GP":
        return None
    flags = blob[3]
    envelope = ENVELOPE_SIZES.get((flags >> 1) & 0b111)
    if envelope is None or flags & EMPTY_GEOMETRY:
        return None
    wkb = blob[GEOPACKAGE_HEADER + envelope :]
    return wkb if len(wkb) > 5 else None


def _text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


@dataclass(frozen=True)
class Site:
    values: tuple[str | None, ...]
    wkb: bytes


def site_of(row: sqlite3.Row, columns: tuple[str, ...], key: str) -> Site | None:
    wkb = wkb_of(row[GEOMETRY])
    values = tuple(_text(row[column]) for column in columns)
    known = dict(zip(columns, values, strict=True))
    if wkb is None or known[key] is None:
        return None
    return Site(values, wkb)


@dataclass(frozen=True)
class SourceTable:
    shape: str
    columns: tuple[str, ...]
    ignored: tuple[str, ...]
    missing: tuple[str, ...]


@dataclass(frozen=True)
class SourceFile:
    path: Path
    tables: tuple[SourceTable, ...]


def table_columns(connection: Connection, layer: SiteLayer) -> tuple[str, ...]:
    rows = connection.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = :table ORDER BY ordinal_position"),
        {"table": layer.table},
    ).scalars()
    return tuple(column for column in rows if column not in COMPUTED)


def _connect(path: Path) -> sqlite3.Connection:
    database = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    database.row_factory = sqlite3.Row
    return database


def open_source(path: Path, wanted: tuple[str, ...], layer: SiteLayer) -> SourceFile:
    if not path.is_file():
        raise ImportRefused(f"Fichier introuvable : {path}")
    database = _connect(path)
    try:
        tables = []
        for shape, table in layer.shapes.items():
            found = [row["name"] for row in database.execute(f'PRAGMA table_info("{table}")')]
            absent = [column for column in (layer.key, GEOMETRY) if column not in found]
            if absent:
                raise ImportRefused(f"Table {table} absente ou sans les colonnes {', '.join(absent)}")
            columns = tuple(column for column in wanted if column in found)
            ignored = tuple(column for column in found if column not in wanted and column not in ("fid", GEOMETRY))
            missing = tuple(column for column in wanted if column not in found)
            tables.append(SourceTable(shape, columns, ignored, missing))
    finally:
        database.close()
    return SourceFile(path, tuple(tables))


def sites(path: Path, table: SourceTable, layer: SiteLayer) -> Iterator[Site | None]:
    database = _connect(path)
    try:
        selected = ", ".join(f'"{column}"' for column in (*table.columns, GEOMETRY))
        for row in database.execute(f'SELECT {selected} FROM "{layer.shapes[table.shape]}" ORDER BY fid'):
            yield site_of(row, table.columns, layer.key)
    finally:
        database.close()


@dataclass(frozen=True)
class ImportResult:
    imported: dict[str, int]
    skipped: int


# Chaque table du fichier passe par une table temporaire chargée par COPY, puis est recopiée avec sa géométrie lue
# par PostGIS et passée en EPSG:3857 ; un code en double garde la première ligne du fichier, une géométrie
# illisible, vide ou hors du Web Mercator est écartée. Les colonnes absentes du fichier restent vides.
def import_sites(connection: Connection, source: SourceFile, layer: SiteLayer) -> ImportResult:
    connection.execute(text(f"DELETE FROM {layer.table}"))
    imported: dict[str, int] = {}
    skipped = 0
    driver = connection.connection.driver_connection
    for table in source.tables:
        quoted = ", ".join(f'"{column}"' for column in table.columns)
        connection.execute(
            text(
                f"""
                CREATE TEMPORARY TABLE {IMPORT_TABLE} (
                    {", ".join(f'"{column}" text' for column in table.columns)}, import_wkb bytea,
                    import_order bigint GENERATED ALWAYS AS IDENTITY
                ) ON COMMIT DROP
                """
            )
        )
        with driver.cursor() as cursor, cursor.copy(f"COPY {IMPORT_TABLE} ({quoted}, import_wkb) FROM STDIN") as copy:
            for site in sites(source.path, table, layer):
                if site is None:
                    skipped += 1
                    continue
                copy.write_row((*site.values, site.wkb))
        read = connection.execute(
            text(
                f"""
                INSERT INTO {layer.table} (shape, {quoted}, geometry)
                SELECT DISTINCT ON ("{layer.key}") :shape, {quoted}, ST_Transform(ST_SetSRID(geometry, 4326), 3857)
                FROM (SELECT *, ST_Force2D(ST_GeomFromWKB(import_wkb)) AS geometry FROM {IMPORT_TABLE}) parsed
                WHERE NOT ST_IsEmpty(geometry) AND ST_YMin(geometry) >= -:max AND ST_YMax(geometry) <= :max
                  AND ST_XMin(geometry) >= -180 AND ST_XMax(geometry) <= 180
                ORDER BY "{layer.key}", import_order
                """
            ),
            {"shape": table.shape, "max": MAX_MERCATOR_LATITUDE},
        ).rowcount
        total = connection.execute(text(f"SELECT count(*) FROM {IMPORT_TABLE}")).scalar_one()
        skipped += total - read
        imported[table.shape] = read
        connection.execute(text(f"DROP TABLE {IMPORT_TABLE}"))
    connection.execute(text(f"ANALYZE {layer.table}"))
    if sum(imported.values()) == 0:
        raise ImportRefused("Aucun site valide dans le fichier")
    return ImportResult(imported=imported, skipped=skipped)


def main(arguments: list[str], layer: SiteLayer, program: str) -> int:
    parser = argparse.ArgumentParser(prog=program)
    parser.add_argument("path", type=Path)
    options = parser.parse_args(arguments)
    try:
        with refonte_transaction() as connection:
            source = open_source(options.path, table_columns(connection, layer), layer)
            result = import_sites(connection, source, layer)
    except ImportRefused as error:
        print(f"Import refusé : {error}", file=sys.stderr)
        return 1
    counts = " et ".join(f"{result.imported.get(shape, 0)} {SHAPE_NAMES[shape]}" for shape in layer.shapes)
    print(f"{layer.label} : import de {counts} ; {result.skipped} lignes écartées (géométrie ou code manquant, ou code en double)")
    for table in source.tables:
        if table.missing:
            print(f"{layer.shapes[table.shape]} : colonnes absentes du fichier, laissées vides : {', '.join(table.missing)}")
        if table.ignored:
            print(f"{layer.shapes[table.shape]} : colonnes du fichier inconnues de la table, ignorées : {', '.join(table.ignored)}")
    return 0
