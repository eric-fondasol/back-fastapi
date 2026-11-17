# Import des ouvrages de la Banque du Sous-Sol (table bss_wells, migration 0047, ADR-0066 du front) depuis
# l'extrait BSS_TOTAL.gpkg du BRGM, lancé à la main dans le conteneur de l'API ; procédure dans
# docs/couches/couches-en-base.md.
#
#   python -m app.domains.layer_catalog.bss <BSS_TOTAL.gpkg>
#
# Remplace en une transaction tous les ouvrages : le relancer avec un nouvel extrait suffit. Le GeoPackage est lu
# avec sqlite3 (pas de GDAL dans l'image) : une géométrie GeoPackage est un en-tête suivi d'un point en WKB.
# Les colonnes copiées sont celles de bss_wells qui existent dans le fichier (même nom) ; la liste fait foi dans
# la migration. Le fichier est ouvert par une URI file:/// (Path.as_uri) : un chemin Windows (C:\apps\…) y est
# converti, ce que ne fait pas une URI « file: » écrite à la main.

import argparse
import re
import sqlite3
import struct
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import Connection, text

from app.database.connection import refonte_transaction

TABLE = "BSS_TOTAL"
GEOMETRY = "geom"
REQUIRED = ("bss_id", "code_log", "lien")
COMPUTED = ("sheet_url", "geometry")
GEOLOGY_CLASSES = {"1", "2", "3", "4", "5", "6"}

# Octets d'enveloppe selon les bits 1 à 3 des drapeaux de l'en-tête GeoPackage (aucune, xy, xyz, xym, xyzm).
ENVELOPE_SIZES = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
GEOPACKAGE_HEADER = 8
WKB_POINT = 1
# Latitude extrême du Web Mercator : au-delà, ST_Transform vers EPSG:3857 diverge.
MAX_MERCATOR_LATITUDE = 85.05112878

# Le champ lien est une formule Excel : "=LIEN_HYPERTEXTE(""http://…?id=01574X0006/SO"" ;""01574X0006"")".
LINK = re.compile(r"https?://[^\"]+")


class ImportRefused(Exception):
    pass


def point_of(blob: bytes | None) -> tuple[float, float] | None:
    if blob is None or len(blob) < GEOPACKAGE_HEADER or blob[:2] != b"GP":
        return None
    flags = blob[3]
    envelope = ENVELOPE_SIZES.get((flags >> 1) & 0b111)
    if envelope is None or flags & 0b10000:
        return None
    wkb = blob[GEOPACKAGE_HEADER + envelope :]
    if len(wkb) < 21:
        return None
    order = "<" if wkb[0] == 1 else ">"
    (geometry_type,) = struct.unpack(f"{order}I", wkb[1:5])
    if geometry_type % 1000 != WKB_POINT:
        return None
    longitude, latitude = struct.unpack(f"{order}dd", wkb[5:21])
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        return None
    return longitude, latitude


# Adresse de la fiche InfoTerre tirée de la formule ; les espaces de certaines références (01705X0006/92 FE) sont
# encodées, sans quoi l'adresse ne serait pas reconnue comme un lien.
def sheet_url_of(link: str | None) -> str | None:
    found = LINK.search(link or "")
    return None if found is None else quote(found.group(0), safe=":/?&=%#")


def _text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


@dataclass(frozen=True)
class Well:
    values: tuple[str | None, ...]
    sheet_url: str
    longitude: float
    latitude: float


def well_of(row: sqlite3.Row, columns: tuple[str, ...]) -> Well | None:
    point = point_of(row[GEOMETRY])
    sheet_url = sheet_url_of(row["lien"])
    values = tuple(_text(row[column]) for column in columns)
    known = dict(zip(columns, values, strict=True))
    if point is None or sheet_url is None or known["bss_id"] is None or known["code_log"] not in GEOLOGY_CLASSES:
        return None
    longitude, latitude = point
    return Well(values, sheet_url, longitude, latitude)


@dataclass(frozen=True)
class SourceFile:
    columns: tuple[str, ...]
    ignored: tuple[str, ...]
    missing: tuple[str, ...]
    wells: Iterator[Well | None]


def table_columns(connection: Connection) -> tuple[str, ...]:
    rows = connection.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = 'bss_wells' ORDER BY ordinal_position")
    ).scalars()
    return tuple(column for column in rows if column not in COMPUTED)


def _rows(database: sqlite3.Connection, columns: tuple[str, ...]) -> Iterator[Well | None]:
    try:
        selected = ", ".join(f'"{column}"' for column in (*columns, GEOMETRY))
        for row in database.execute(f'SELECT {selected} FROM "{TABLE}"'):
            yield well_of(row, columns)
    finally:
        database.close()


def open_source(path: Path, wanted: tuple[str, ...]) -> SourceFile:
    if not path.is_file():
        raise ImportRefused(f"Fichier introuvable : {path}")
    database = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    database.row_factory = sqlite3.Row
    found = [row["name"] for row in database.execute(f'PRAGMA table_info("{TABLE}")')]
    absent = [column for column in (*REQUIRED, GEOMETRY) if column not in found]
    if absent:
        database.close()
        raise ImportRefused(f"Table {TABLE} absente ou sans les colonnes {', '.join(absent)}")
    columns = tuple(column for column in wanted if column in found)
    ignored = tuple(column for column in found if column not in wanted and column not in ("fid", GEOMETRY))
    missing = tuple(column for column in wanted if column not in found)
    return SourceFile(columns, ignored, missing, _rows(database, columns))


@dataclass(frozen=True)
class ImportResult:
    imported: int
    skipped: int


# Les ouvrages passent par une table temporaire chargée par COPY, puis sont recopiés avec leur point en
# EPSG:3857 ; un identifiant en double garde la première ligne. Les colonnes absentes du fichier restent vides.
# Les colonnes de travail sont préfixées point_ : le fichier a déjà ses propres longitude et latitude (texte).
def import_wells(connection: Connection, source: SourceFile) -> ImportResult:
    quoted = ", ".join(f'"{column}"' for column in source.columns)
    connection.execute(
        text(
            f"""
            CREATE TEMPORARY TABLE bss_import (
                {", ".join(f'"{column}" text' for column in source.columns)},
                point_sheet_url text, point_longitude float8, point_latitude float8
            ) ON COMMIT DROP
            """
        )
    )
    skipped = 0
    driver = connection.connection.driver_connection
    with driver.cursor() as cursor, cursor.copy(f"COPY bss_import ({quoted}, point_sheet_url, point_longitude, point_latitude) FROM STDIN") as copy:
        for well in source.wells:
            if well is None:
                skipped += 1
                continue
            copy.write_row((*well.values, well.sheet_url, well.longitude, well.latitude))
    connection.execute(text("DELETE FROM bss_wells"))
    imported = connection.execute(
        text(
            f"""
            INSERT INTO bss_wells ({quoted}, sheet_url, geometry)
            SELECT DISTINCT ON (bss_id) {quoted}, point_sheet_url,
                   ST_Transform(ST_SetSRID(ST_MakePoint(point_longitude, greatest(least(point_latitude, :max), -:max)), 4326), 3857)
            FROM bss_import
            ORDER BY bss_id
            """
        ),
        {"max": MAX_MERCATOR_LATITUDE},
    ).rowcount
    connection.execute(text("ANALYZE bss_wells"))
    if imported == 0:
        raise ImportRefused("Aucun ouvrage valide dans le fichier")
    return ImportResult(imported=imported, skipped=skipped)


def main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.domains.layer_catalog.bss")
    parser.add_argument("path", type=Path)
    options = parser.parse_args(arguments)
    try:
        with refonte_transaction() as connection:
            source = open_source(options.path, table_columns(connection))
            result = import_wells(connection, source)
    except ImportRefused as error:
        print(f"Import refusé : {error}", file=sys.stderr)
        return 1
    print(f"Ouvrages BSS : {result.imported} importés, {result.skipped} écartés (géométrie, classe ou lien manquant)")
    if source.missing:
        print(f"Colonnes absentes du fichier, laissées vides : {', '.join(source.missing)}")
    if source.ignored:
        print(f"Colonnes du fichier inconnues de la table, ignorées : {', '.join(source.ignored)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
