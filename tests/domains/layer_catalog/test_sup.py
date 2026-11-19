import importlib.util
import math
import sqlite3
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.auth import current_user
from app.domains.layer_catalog import site_layers, sources
from app.domains.layer_catalog.sup import LAYER
from app.main import app

VERSIONS = Path(__file__).parents[3] / "migrations" / "versions"
CODE = "fr-georisques-sup"
MVT = "application/vnd.mapbox-vector-tile"
ROUEN = (1.0993, 49.4431)
COLUMNS = "code_metier TEXT, id_inventaire_classification TEXT, nom_etablissement TEXT, code_insee TEXT, nom_commune TEXT, date_ap TEXT, url_fiche TEXT"


def migration(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def square(longitude, latitude, side=0.001):
    ring = [(longitude, latitude), (longitude + side, latitude), (longitude + side, latitude + side), (longitude, latitude + side), (longitude, latitude)]
    polygon = struct.pack("<BII", 1, 3, 1) + struct.pack("<I", len(ring)) + b"".join(struct.pack("<dd", *xy) for xy in ring)
    wkb = struct.pack("<BII", 1, 6, 1) + polygon
    return b"GP\x00\x03" + struct.pack("<i", 4326) + struct.pack("<dddd", longitude, longitude + side, latitude, latitude + side) + wkb


def fiche(code):
    return f"https://fiches-risques.brgm.fr/georisques/infosols/classification/{code}"


def write_geopackage(path, rows):
    database = sqlite3.connect(path)
    database.execute(f"CREATE TABLE SSP_CLASSIF_SUP_GE (fid INTEGER PRIMARY KEY, geom BLOB, {COLUMNS})")
    database.executemany(
        "INSERT INTO SSP_CLASSIF_SUP_GE (geom, code_metier, id_inventaire_classification, nom_etablissement, code_insee, nom_commune, date_ap, url_fiche) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
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
        migration("0054_sup_sites").seed(connection)
    return refonte_database


@pytest.fixture
def client(database, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("les servitudes SUP en base n'appellent aucun service")

    monkeypatch.setattr(sources.httpx, "get", no_network)
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def imported(database, path):
    with database.begin() as connection:
        return site_layers.import_sites(connection, site_layers.open_source(path, site_layers.table_columns(connection, LAYER), LAYER), LAYER)


def rouen_file(tmp_path):
    return write_geopackage(
        tmp_path / "sup.gpkg",
        [
            (square(*ROUEN), "SSP00073030301", None, "Ancienne raffinerie", "76540", "ROUEN", "2018-02-12", fiche("SSP00073030301")),
            (square(*ROUEN), "SSP00073030301", None, "Ancienne raffinerie", "76451", "PETIT-QUEVILLY", "2018-02-12", fiche("SSP00073030301")),
            (None, "SSP000002", None, "Sans géométrie", "76540", "ROUEN", None, fiche("SSP000002")),
        ],
    )


def test_the_footprints_are_imported_once_per_easement_from_the_only_table_of_the_file(database, tmp_path):
    assert imported(database, rouen_file(tmp_path)) == site_layers.ImportResult(imported={"polygon": 1}, skipped=2)

    with database.connect() as connection:
        rows = connection.execute(text("SELECT shape, code_metier, nom_commune, date_ap, GeometryType(geometry), ST_SRID(geometry) FROM sup_sites")).all()
    assert [tuple(row) for row in rows] == [("polygon", "SSP00073030301", "ROUEN", "2018-02-12", "MULTIPOLYGON", 3857)]


def test_the_layer_is_served_as_vector_tiles_from_the_minimal_zoom(client, database, tmp_path):
    imported(database, rouen_file(tmp_path))

    layer = next(layer for layer in client.get("/layer-catalog").json()["layers"] if layer["code"] == CODE)
    assert (layer["kind"], layer["url"], layer["legendUrl"], layer["params"]) == ("sup", None, None, {"color": "#018571"})

    tile = client.get("/layer-catalog/{}/tiles/{}/{}/{}".format(CODE, *tile_of(*ROUEN, 14)))
    assert (tile.status_code, tile.headers["content-type"]) == (200, MVT)
    for content in (b"features", b"SSP00073030301", b"Ancienne raffinerie", b"date_ap", b"classification/SSP00073030301"):
        assert content in tile.content

    below = client.get("/layer-catalog/{}/tiles/{}/{}/{}".format(CODE, *tile_of(*ROUEN, 11)))
    assert (below.status_code, below.content) == (200, b"")


def test_the_layer_comes_right_after_the_sis_sectors_in_its_category(client):
    codes = [layer["code"] for layer in client.get("/layer-catalog").json()["layers"] if layer["code"].startswith("fr-georisques-")]
    assert codes.index(CODE) == codes.index("fr-georisques-sis") + 1
