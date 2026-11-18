# Import des milieux humides du sud du Québec (table quebec_wetlands, migration 0049, ADR-0069 du front) depuis
# mh_2023.gpkg, lancé à la main dans le conteneur de l'API ; procédure dans docs/couches/couches-en-base.md.
#
#   python -m app.domains.layer_catalog.wetlands <mh_2023.gpkg>
#
# Comme pour CASIAS (casias.py), le GeoPackage est lu avec sqlite3 et sa géométrie confiée à PostGIS une fois
# l'en-tête retiré ; l'import remplace en une transaction tous les milieux, le relancer avec une nouvelle version
# suffit. Les colonnes du fichier sont en majuscules (export ArcGIS) : elles sont rapprochées de celles de la table
# sans tenir compte de la casse. Deux objets du fichier de novembre 2023 sont des MULTISURFACE : toute géométrie
# passe par ST_CurveToLine, qui en fait des MULTIPOLYGON et laisse les autres intactes. ST_HasArc ne suffit pas à
# les repérer : une MULTISURFACE faite de polygones simples n'a pas d'arc, et serait restée telle quelle.

import argparse
import sqlite3
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection, text

from app.database.connection import refonte_transaction
from app.domains.layer_catalog.casias import MAX_MERCATOR_LATITUDE, ImportRefused, wkb_of

TABLE = "milieux_humides_sudqc_nov2023"
GEOMETRY = "geom"
KEY = "globalid"
CLASS = "classe"
KNOWN_CLASS = "AND (classe IS NULL OR classe IN (SELECT code FROM quebec_wetland_classes))"
COMPUTED = ("geometry",)


def _text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


@dataclass(frozen=True)
class Wetland:
    values: tuple[str | None, ...]
    wkb: bytes


@dataclass(frozen=True)
class SourceFile:
    path: Path
    columns: tuple[str, ...]
    names: tuple[str, ...]
    ignored: tuple[str, ...]
    missing: tuple[str, ...]


def table_columns(connection: Connection) -> tuple[str, ...]:
    rows = connection.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = 'quebec_wetlands' ORDER BY ordinal_position")
    ).scalars()
    return tuple(column for column in rows if column not in COMPUTED)


def _connect(path: Path) -> sqlite3.Connection:
    database = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    database.row_factory = sqlite3.Row
    return database


def open_source(path: Path, wanted: tuple[str, ...]) -> SourceFile:
    if not path.is_file():
        raise ImportRefused(f"Fichier introuvable : {path}")
    database = _connect(path)
    try:
        found = {row["name"].lower(): row["name"] for row in database.execute(f'PRAGMA table_info("{TABLE}")')}
    finally:
        database.close()
    absent = [column for column in (KEY, GEOMETRY) if column not in found]
    if absent:
        raise ImportRefused(f"Table {TABLE} absente ou sans les colonnes {', '.join(absent)}")
    columns = tuple(column for column in wanted if column in found)
    return SourceFile(
        path=path,
        columns=columns,
        names=tuple(found[column] for column in columns),
        ignored=tuple(name for column, name in found.items() if column not in wanted and column not in ("fid", GEOMETRY)),
        missing=tuple(column for column in wanted if column not in found),
    )


def wetland_of(row: sqlite3.Row, source: SourceFile) -> Wetland | None:
    wkb = wkb_of(row[GEOMETRY])
    values = tuple(_text(row[name]) for name in source.names)
    if wkb is None or values[source.columns.index(KEY)] is None:
        return None
    return Wetland(values, wkb)


def wetlands(source: SourceFile) -> Iterator[Wetland | None]:
    database = _connect(source.path)
    try:
        selected = ", ".join(f'"{name}"' for name in (*source.names, GEOMETRY))
        for row in database.execute(f'SELECT {selected} FROM "{TABLE}"'):
            yield wetland_of(row, source)
    finally:
        database.close()


def _unknown_classes(connection: Connection) -> tuple[str, ...]:
    rows = connection.execute(
        text(
            """
            SELECT DISTINCT classe FROM wetlands_import
            WHERE classe IS NOT NULL AND classe NOT IN (SELECT code FROM quebec_wetland_classes)
            ORDER BY classe
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
# courbes converties en polygones et passée en EPSG:3857 ; une clé en double garde la première ligne, une
# géométrie illisible, vide ou hors du Web Mercator est écartée, comme un milieu d'une classe absente de
# quebec_wetland_classes (la clé étrangère le refuserait, et l'import entier avec lui) : ces classes sont
# signalées. Les colonnes absentes du fichier restent vides.
def import_wetlands(connection: Connection, source: SourceFile) -> ImportResult:
    connection.execute(text("DELETE FROM quebec_wetlands"))
    quoted = ", ".join(f'"{column}"' for column in source.columns)
    connection.execute(
        text(
            f"""
            CREATE TEMPORARY TABLE wetlands_import (
                {", ".join(f'"{column}" text' for column in source.columns)}, import_wkb bytea
            ) ON COMMIT DROP
            """
        )
    )
    skipped = 0
    driver = connection.connection.driver_connection
    with driver.cursor() as cursor, cursor.copy(f"COPY wetlands_import ({quoted}, import_wkb) FROM STDIN") as copy:
        for wetland in wetlands(source):
            if wetland is None:
                skipped += 1
                continue
            copy.write_row((*wetland.values, wetland.wkb))
    imported = connection.execute(
        text(
            f"""
            INSERT INTO quebec_wetlands ({quoted}, geometry)
            SELECT DISTINCT ON ({KEY}) {quoted}, ST_Transform(ST_SetSRID(geometry, 4326), 3857)
            FROM (
                SELECT *, ST_Force2D(ST_CurveToLine(ST_GeomFromWKB(import_wkb))) AS geometry FROM wetlands_import
            ) parsed
            WHERE NOT ST_IsEmpty(geometry) AND ST_YMin(geometry) >= -:max AND ST_YMax(geometry) <= :max
              AND ST_XMin(geometry) >= -180 AND ST_XMax(geometry) <= 180
              {KNOWN_CLASS if CLASS in source.columns else ""}
            ORDER BY {KEY}
            """
        ),
        {"max": MAX_MERCATOR_LATITUDE},
    ).rowcount
    total = connection.execute(text("SELECT count(*) FROM wetlands_import")).scalar_one()
    unknown = _unknown_classes(connection) if CLASS in source.columns else ()
    connection.execute(text("DROP TABLE wetlands_import"))
    connection.execute(text("ANALYZE quebec_wetlands"))
    if imported == 0:
        raise ImportRefused("Aucun milieu humide valide dans le fichier")
    return ImportResult(imported=imported, skipped=skipped + total - imported, unknown_classes=unknown)


def main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.domains.layer_catalog.wetlands")
    parser.add_argument("path", type=Path)
    options = parser.parse_args(arguments)
    try:
        with refonte_transaction() as connection:
            source = open_source(options.path, table_columns(connection))
            result = import_wetlands(connection, source)
    except ImportRefused as error:
        print(f"Import refusé : {error}", file=sys.stderr)
        return 1
    print(f"Milieux humides : {result.imported} importés, {result.skipped} écartés (géométrie ou clé manquante, ou clé en double)")
    if result.unknown_classes:
        print(f"Classes absentes de quebec_wetland_classes, milieux écartés : {', '.join(result.unknown_classes)}")
    if source.missing:
        print(f"Colonnes absentes du fichier, laissées vides : {', '.join(source.missing)}")
    if source.ignored:
        print(f"Colonnes du fichier inconnues de la table, ignorées : {', '.join(source.ignored)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
