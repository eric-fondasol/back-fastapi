# Import des données d'une couche stockée en base (migration 0038, ADR-0062 du front), lancé à la main dans
# le conteneur de l'API ; procédure complète, préparation des fichiers comprise, dans docs/couches/couches-en-base.md.
#
#   python -m app.domains.layer_catalog.imports features <code> <fichier.geojson>
#   python -m app.domains.layer_catalog.imports tiles <code> <dossier z/x/y>
#   python -m app.domains.layer_catalog.imports legend <code> <image>
#
# Chaque import remplace en une transaction ce que la couche avait déjà : le relancer avec un fichier corrigé
# suffit. La couche doit exister au catalogue avec le bon type (database pour les objets, database-tiles pour
# les tuiles).

import argparse
import json
import mimetypes
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

from app.database.connection import refonte_transaction

# Lignes envoyées à la base par lot : assez pour limiter les allers-retours, assez peu pour la mémoire.
BATCH_SIZE = 500
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


class ImportRefused(Exception):
    pass


def _layer_id(connection: Connection, code: str, kind: str) -> Any:
    row = connection.execute(text("SELECT id, kind FROM catalog_layers WHERE code = :code"), {"code": code}).first()
    if row is None:
        raise ImportRefused(f"Couche {code} absente du catalogue")
    if row.kind != kind:
        raise ImportRefused(f"La couche {code} est de type {row.kind}, l'import attend {kind}")
    return row.id


def _batches(rows: Iterator[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) == BATCH_SIZE:
            yield batch
            batch = []
    if batch:
        yield batch


# Objets d'un FeatureCollection en longitude, latitude (EPSG:4326). Une géométrie invalide est réparée par
# PostGIS (ST_MakeValid) ; un objet sans géométrie est ignoré. Rend le nombre d'objets importés.
def import_features(connection: Connection, code: str, collection: dict[str, Any]) -> int:
    layer_id = _layer_id(connection, code, "database")
    features = collection.get("features") if isinstance(collection, dict) else None
    if not isinstance(features, list):
        raise ImportRefused("Le fichier n'est pas un FeatureCollection GeoJSON")
    connection.execute(text("DELETE FROM catalog_layer_features WHERE layer_id = :layer_id"), {"layer_id": layer_id})
    rows = (
        {
            "layer_id": layer_id,
            "geometry": json.dumps(feature["geometry"]),
            "properties": json.dumps(feature.get("properties") or {}, ensure_ascii=False),
        }
        for feature in features
        if isinstance(feature, dict) and feature.get("geometry")
    )
    count = 0
    for batch in _batches(rows):
        connection.execute(
            text(
                """
                INSERT INTO catalog_layer_features (layer_id, geometry, properties)
                VALUES (:layer_id, ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326)), CAST(:properties AS jsonb))
                """
            ),
            batch,
        )
        count += len(batch)
    return count


def _tile_files(folder: Path) -> Iterator[tuple[int, int, int, Path]]:
    for path in sorted(folder.glob("*/*/*")):
        if path.suffix.lower() in IMAGE_TYPES and path.parent.name.isdigit() and path.parent.parent.name.isdigit() and path.stem.isdigit():
            yield int(path.parent.parent.name), int(path.parent.name), int(path.stem), path


# Tuiles d'un dossier z/x/y.<ext> en grille XYZ (celle de gdal2tiles --xyz, origine en haut à gauche).
# Rend le nombre de tuiles importées.
def import_tiles(connection: Connection, code: str, folder: Path) -> int:
    layer_id = _layer_id(connection, code, "database-tiles")
    connection.execute(text("DELETE FROM catalog_layer_tiles WHERE layer_id = :layer_id"), {"layer_id": layer_id})
    rows = (
        {"layer_id": layer_id, "z": z, "x": x, "y": y, "content": path.read_bytes(), "content_type": IMAGE_TYPES[path.suffix.lower()]}
        for z, x, y, path in _tile_files(folder)
    )
    count = 0
    for batch in _batches(rows):
        connection.execute(
            text(
                """
                INSERT INTO catalog_layer_tiles (layer_id, z, x, y, content, content_type)
                VALUES (:layer_id, :z, :x, :y, :content, :content_type)
                """
            ),
            batch,
        )
        count += len(batch)
    if count == 0:
        raise ImportRefused(f"Aucune tuile z/x/y dans {folder}")
    return count


# Image de légende d'une couche, quel que soit son type.
def import_legend(connection: Connection, code: str, content: bytes, content_type: str) -> None:
    row = connection.execute(text("SELECT id FROM catalog_layers WHERE code = :code"), {"code": code}).first()
    if row is None:
        raise ImportRefused(f"Couche {code} absente du catalogue")
    if not content_type.startswith("image/"):
        raise ImportRefused(f"La légende doit être une image ({content_type})")
    connection.execute(
        text(
            """
            INSERT INTO catalog_layer_legends (layer_id, content, content_type) VALUES (:layer_id, :content, :content_type)
            ON CONFLICT (layer_id) DO UPDATE SET content = excluded.content, content_type = excluded.content_type, updated_at = now()
            """
        ),
        {"layer_id": row.id, "content": content, "content_type": content_type},
    )


def main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.domains.layer_catalog.imports")
    parser.add_argument("what", choices=["features", "tiles", "legend"])
    parser.add_argument("code")
    parser.add_argument("path", type=Path)
    options = parser.parse_args(arguments)
    try:
        with refonte_transaction() as connection:
            if options.what == "features":
                count = import_features(connection, options.code, json.loads(options.path.read_text(encoding="utf-8")))
                print(f"{options.code} : {count} objets importés")
            elif options.what == "tiles":
                count = import_tiles(connection, options.code, options.path)
                print(f"{options.code} : {count} tuiles importées")
            else:
                content_type = mimetypes.guess_type(options.path.name)[0] or ""
                import_legend(connection, options.code, options.path.read_bytes(), content_type)
                print(f"{options.code} : légende importée")
    except ImportRefused as error:
        print(f"Import refusé : {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
