import importlib.util
import math
import sqlite3
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.auth import current_user
from app.domains.layer_catalog import polygon_layers, sources
from app.domains.layer_catalog.wetlands import LAYER
from app.main import app

VERSIONS = Path(__file__).parents[3] / "migrations" / "versions"
CODE = "ca-qc-milieux-humides"
MVT = "application/vnd.mapbox-vector-tile"
LAVAL = (-73.75, 45.6)
COLUMNS = "GLOBALID TEXT, CLASSE TEXT, MH_HA REAL, CONF_CLASS MEDIUMINT, PROJET TEXT, COLONNE_NOUVELLE TEXT"


def migration(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def geopackage(wkb, envelope):
    return b"GP\x00\x03" + struct.pack("<i", 4326) + struct.pack("<dddd", *envelope) + wkb


def ring_of(longitude, latitude, side):
    ring = [(longitude, latitude), (longitude + side, latitude), (longitude + side, latitude + side), (longitude, latitude + side), (longitude, latitude)]
    return struct.pack("<I", len(ring)) + b"".join(struct.pack("<dd", *xy) for xy in ring)


def square(longitude, latitude, side=0.001, collection=6):
    polygon = struct.pack("<BII", 1, 3, 1) + ring_of(longitude, latitude, side)
    return geopackage(struct.pack("<BII", 1, collection, 1) + polygon, (longitude, longitude + side, latitude, latitude + side))


def multisurface(longitude, latitude, side=0.001):
    return square(longitude, latitude, side, collection=12)


def write_geopackage(path, rows):
    database = sqlite3.connect(path)
    database.execute(f"CREATE TABLE milieux_humides_sudqc_nov2023 (fid INTEGER PRIMARY KEY, geom BLOB, {COLUMNS})")
    database.executemany(
        "INSERT INTO milieux_humides_sudqc_nov2023 (geom, GLOBALID, CLASSE, MH_HA, CONF_CLASS, PROJET) VALUES (?, ?, ?, ?, ?, ?)", rows
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
    return refonte_database


@pytest.fixture
def client(database, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("les milieux humides en base n'appellent aucun service")

    monkeypatch.setattr(sources.httpx, "get", no_network)
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def imported(database, path):
    with database.begin() as connection:
        return polygon_layers.import_polygons(connection, polygon_layers.open_source(path, polygon_layers.table_columns(connection, LAYER), LAYER), LAYER)


def laval_file(tmp_path):
    return write_geopackage(tmp_path / "mh.gpkg", [(square(*LAVAL), "{A1}", "MS", 23.088, 3, "Laval (2010)")])


def test_the_import_replaces_the_wetlands_and_skips_the_unusable_rows(database, tmp_path):
    path = write_geopackage(
        tmp_path / "mh.gpkg",
        [
            (square(*LAVAL), "{A1}", "MS", 23.088, 3, "Laval (2010)"),
            (square(-72.0, 48.5), "{A2}", "TB", 0.5, 2, " "),
            (square(*LAVAL), "{A1}", "ME", 1.0, 1, "Doublon"),
            (None, "{A3}", "ME", 1.0, 1, "Sans géométrie"),
            (square(*LAVAL), "\xa0", "ME", 1.0, 1, "Sans clé"),
        ],
    )

    assert imported(database, path) == polygon_layers.ImportResult(imported=2, skipped=3)
    assert imported(database, path) == polygon_layers.ImportResult(imported=2, skipped=3)

    with database.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT globalid, classe, mh_ha, conf_class, projet, notes, GeometryType(geometry), ST_SRID(geometry), "
                "round(ST_XMin(ST_Transform(geometry, 4326))::numeric, 4)::float8 FROM quebec_wetlands ORDER BY globalid"
            )
        ).all()
    assert [tuple(row) for row in rows] == [
        ("{A1}", "MS", "23.088", "3", "Laval (2010)", None, "MULTIPOLYGON", 3857, -73.75),
        ("{A2}", "TB", "0.5", "2", None, None, "MULTIPOLYGON", 3857, -72.0),
    ]


def test_a_wetland_of_a_class_missing_from_the_class_table_is_skipped_and_reported(database, tmp_path):
    path = write_geopackage(
        tmp_path / "mh.gpkg",
        [(square(*LAVAL), "{A1}", "MS", 1.0, 3, "Laval"), (square(*LAVAL), "{A2}", "ZZ", 1.0, 3, "Laval"), (square(*LAVAL), "{A3}", None, 1.0, 3, "Laval")],
    )

    assert imported(database, path) == polygon_layers.ImportResult(imported=2, skipped=1, unknown_classes=("ZZ",))


def test_the_wetlands_table_refuses_a_class_missing_from_the_class_table(database):
    with pytest.raises(IntegrityError), database.begin() as connection:
        connection.execute(
            text("INSERT INTO quebec_wetlands (globalid, classe, geometry) VALUES ('{A1}', 'ZZ', ST_SetSRID(ST_MakePoint(0, 0), 3857))")
        )


def test_a_multisurface_without_arc_becomes_a_multipolygon(database, tmp_path):
    imported(database, write_geopackage(tmp_path / "mh.gpkg", [(multisurface(*LAVAL), "{A1}", "ME", 1.0, 3, "Laval")]))

    with database.connect() as connection:
        assert connection.execute(text("SELECT GeometryType(geometry) FROM quebec_wetlands")).scalar_one() == "MULTIPOLYGON"


def test_the_uppercase_columns_of_the_file_are_matched_to_those_of_the_table(database, tmp_path):
    with database.connect() as connection:
        found = polygon_layers.open_source(laval_file(tmp_path), polygon_layers.table_columns(connection, LAYER), LAYER)

    assert found.columns == ("globalid", "classe", "conf_class", "projet", "mh_ha")
    assert found.names == ("GLOBALID", "CLASSE", "CONF_CLASS", "PROJET", "MH_HA")
    assert found.ignored == ("COLONNE_NOUVELLE",)
    assert "notes" in found.missing and len(found.missing) == 25


def test_a_file_without_the_wetlands_table_is_refused(database, tmp_path):
    path = tmp_path / "autre.gpkg"
    sqlite3.connect(path).execute("CREATE TABLE autre (fid INTEGER, geom BLOB)").connection.commit()

    with pytest.raises(polygon_layers.ImportRefused, match="milieux_humides_sudqc_nov2023"):
        imported(database, path)


def test_the_layer_is_served_as_vector_tiles_coloured_by_class(client, database, tmp_path):
    imported(database, laval_file(tmp_path))

    layer = next(layer for layer in client.get("/layer-catalog").json()["layers"] if layer["code"] == CODE)
    assert (layer["kind"], layer["url"], layer["legendUrl"], layer["country"], layer["category"]) == ("wetlands", None, None, "ca", "eau-surface")
    assert layer["params"]["color"] == "#97c919"
    assert layer["params"]["classes"]["property"] == "classe"
    assert [value["value"] for value in layer["params"]["classes"]["values"]] == ["BG", "FN", "TB", "ME", "MS", "PH", "EP"]
    assert layer["params"]["classes"]["values"][3] == {"value": "ME", "color": "#55ff00", "label": {"fr": "Marécage", "en": "Swamp"}}

    z, x, y = tile_of(*LAVAL, 14)
    tile = client.get(f"/layer-catalog/{CODE}/tiles/{z}/{x}/{y}")
    assert (tile.status_code, tile.headers["content-type"]) == (200, MVT)
    for content in (b"features", b"{A1}", b"classe", b"MS", b"mh_ha", b"Laval (2010)"):
        assert content in tile.content

    elsewhere = client.get(f"/layer-catalog/{CODE}/tiles/14/0/0")
    assert (elsewhere.status_code, elsewhere.content) == (200, b"")


def test_a_colour_changed_in_the_class_table_reaches_the_catalogue(client, database):
    with database.begin() as connection:
        connection.execute(text("UPDATE quebec_wetland_classes SET color = '#2e9e00' WHERE code = 'ME'"))

    layer = next(layer for layer in client.get("/layer-catalog").json()["layers"] if layer["code"] == CODE)
    assert layer["params"]["classes"]["values"][3]["color"] == "#2e9e00"


def test_below_the_minimal_zoom_the_tile_is_empty(client, database, tmp_path):
    imported(database, laval_file(tmp_path))

    below = client.get("/layer-catalog/{}/tiles/{}/{}/{}".format(CODE, *tile_of(*LAVAL, 11)))
    at = client.get("/layer-catalog/{}/tiles/{}/{}/{}".format(CODE, *tile_of(*LAVAL, 12)))

    assert (below.status_code, below.content) == (200, b"")
    assert at.status_code == 200 and b"{A1}" in at.content
