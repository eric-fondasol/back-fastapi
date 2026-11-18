import importlib.util
import math
import sqlite3
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.auth import current_user
from app.domains.layer_catalog import polygon_layers, sources
from app.domains.layer_catalog.potential_wetlands import LAYER
from app.main import app

VERSIONS = Path(__file__).parents[3] / "migrations" / "versions"
CODE = "ca-qc-milieux-humides-potentiels"
MVT = "application/vnd.mapbox-vector-tile"
LAVAL = (-73.75, 45.6)
COLUMNS = "OBJECTID INTEGER, SOURCE TEXT, CONFIANCE TEXT, SUPERFICIE REAL, CLASSE TEXT, TYPE TEXT, PHYSIONOMIE TEXT"
SIDE_METRES = 100


def migration(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lambert(database, longitude, latitude):
    with database.connect() as connection:
        row = connection.execute(
            text("SELECT ST_X(p), ST_Y(p) FROM (SELECT ST_Transform(ST_SetSRID(ST_MakePoint(:x, :y), 4326), 32198) AS p) projected"),
            {"x": longitude, "y": latitude},
        ).one()
    return row[0], row[1]


def square(x, y, side=SIDE_METRES):
    ring = [(x, y), (x + side, y), (x + side, y + side), (x, y + side), (x, y)]
    polygon = struct.pack("<BII", 1, 3, 1) + struct.pack("<I", len(ring)) + b"".join(struct.pack("<dd", *xy) for xy in ring)
    wkb = struct.pack("<BII", 1, 6, 1) + polygon
    return b"GP\x00\x03" + struct.pack("<i", 32198) + struct.pack("<dddd", x, x + side, y, y + side) + wkb


def write_geopackage(path, rows):
    database = sqlite3.connect(path)
    database.execute(f"CREATE TABLE mh_potentiel_qc (fid INTEGER PRIMARY KEY, geom BLOB, {COLUMNS})")
    database.executemany(
        "INSERT INTO mh_potentiel_qc (geom, OBJECTID, SOURCE, CONFIANCE, SUPERFICIE, CLASSE, TYPE, PHYSIONOMIE) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    database.commit()
    database.close()
    return path


def tile_of(longitude, latitude, zoom):
    x = int((longitude + 180) / 360 * 2**zoom)
    y = int((1 - math.asinh(math.tan(math.radians(latitude))) / math.pi) / 2 * 2**zoom)
    return zoom, x, y


@pytest.fixture
def database(refonte_database):
    with refonte_database.begin() as connection:
        migration("0007_layer_catalog").seed(connection)
        migration("0008_layer_catalog_france").seed(connection)
        migration("0049_quebec_wetlands").seed(connection)
        migration("0050_quebec_potential_wetlands").seed(connection)
    return refonte_database


@pytest.fixture
def client(database, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("les milieux humides potentiels en base n'appellent aucun service")

    monkeypatch.setattr(sources.httpx, "get", no_network)
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def imported(database, path):
    with database.begin() as connection:
        return polygon_layers.import_polygons(connection, polygon_layers.open_source(path, polygon_layers.table_columns(connection, LAYER), LAYER), LAYER)


def laval_file(database, tmp_path):
    return write_geopackage(
        tmp_path / "mh_potentiel.gpkg", [(square(*lambert(database, *LAVAL)), 1, "IEQM", "Bon", 4.2, "Marécage", "Marécage", "arborescent")]
    )


def test_the_lambert_polygons_are_imported_in_web_mercator_and_the_unusable_rows_skipped(database, tmp_path):
    laval = square(*lambert(database, *LAVAL))
    path = write_geopackage(
        tmp_path / "mh_potentiel.gpkg",
        [
            (laval, 1, "IEQM", "Bon", 4.2, "Marécage", "Marécage", "arborescent"),
            (laval, 2, "MH_DETAIL", "Excellent", 22.99, "Marais", "Marais", None),
            (laval, 1, "IEQM", "Moyen", 1.0, "Marais", "Marais", None),
            (laval, 3, "PIEN", "Bon", 1.0, "Classe inconnue", "Tourbière", None),
            (None, 4, "IEQM", "Bon", 1.0, "Marais", "Marais", None),
        ],
    )

    assert imported(database, path) == polygon_layers.ImportResult(imported=2, skipped=3, unknown_classes=("Classe inconnue",))
    assert imported(database, path) == polygon_layers.ImportResult(imported=2, skipped=3, unknown_classes=("Classe inconnue",))

    with database.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT objectid, classe, source, confiance, superficie, physionomie, GeometryType(geometry), ST_SRID(geometry), "
                "round(ST_XMin(ST_Transform(geometry, 4326))::numeric, 3)::float8, round(ST_YMin(ST_Transform(geometry, 4326))::numeric, 3)::float8 "
                "FROM quebec_potential_wetlands ORDER BY objectid"
            )
        ).all()
    assert [tuple(row) for row in rows] == [
        ("1", "Marécage", "IEQM", "Bon", "4.2", "arborescent", "MULTIPOLYGON", 3857, -73.75, 45.6),
        ("2", "Marais", "MH_DETAIL", "Excellent", "22.99", None, "MULTIPOLYGON", 3857, -73.75, 45.6),
    ]


def test_the_spatial_index_is_rebuilt_after_the_import(database, tmp_path):
    imported(database, laval_file(database, tmp_path))

    with database.connect() as connection:
        index = connection.execute(text("SELECT indexdef FROM pg_indexes WHERE indexname = 'quebec_potential_wetlands_geometry'")).scalar_one()
    assert "gist (geometry)" in index


def test_the_layer_lists_its_classes_with_their_outline_from_the_class_table(client, database):
    layers = {layer["code"]: layer for layer in client.get("/layer-catalog").json()["layers"]}

    layer = layers[CODE]
    assert (layer["kind"], layer["url"], layer["legendUrl"], layer["country"], layer["category"]) == ("potential-wetlands", None, None, "ca", "eau-surface")
    assert (layer["params"]["color"], layer["params"]["fillOpacity"], layer["params"]["classes"]["property"]) == ("#cccccc", 0.5, "classe")
    values = layer["params"]["classes"]["values"]
    assert len(values) == 10
    assert values[3] == {"value": "Marécage", "color": "#a3ff73", "outline": "#70a800", "label": {"fr": "Marécage indifférencié", "en": "Undifferentiated swamp"}}
    assert all("outline" not in value for value in layers["ca-qc-milieux-humides"]["params"]["classes"]["values"])


def test_the_layer_is_served_as_vector_tiles_from_the_minimal_zoom(client, database, tmp_path):
    imported(database, laval_file(database, tmp_path))

    tile = client.get("/layer-catalog/{}/tiles/{}/{}/{}".format(CODE, *tile_of(*LAVAL, 14)))
    assert (tile.status_code, tile.headers["content-type"]) == (200, MVT)
    for content in (b"features", b"objectid", "Marécage".encode(), b"IEQM", b"arborescent", b"superficie"):
        assert content in tile.content

    below = client.get("/layer-catalog/{}/tiles/{}/{}/{}".format(CODE, *tile_of(*LAVAL, 11)))
    assert (below.status_code, below.content) == (200, b"")
