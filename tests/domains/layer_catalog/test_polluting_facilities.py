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
from app.domains.layer_catalog.polluting_facilities import LAYER
from app.main import app

VERSIONS = Path(__file__).parents[3] / "migrations" / "versions"
CODE = "fr-georisques-etablissements-pollueurs"
MVT = "application/vnd.mapbox-vector-tile"
SAINT_LO = (1.0906, 49.1158)
COLUMNS = "identifiant TEXT, idetab TEXT, nom TEXT, codeape TEXT, cp TEXT, url_fiche TEXT"


def migration(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def point(longitude, latitude):
    return b"GP\x00\x01" + struct.pack("<i", 4326) + struct.pack("<BIdd", 1, 1, longitude, latitude)


def fiche(idetab):
    return f"https://www.georisques.gouv.fr/risques/registre-des-emissions-polluantes/etablissement/details/{idetab}"


def write_geopackage(path, rows):
    database = sqlite3.connect(path)
    database.execute(f"CREATE TABLE ETABLISSEMENTS_POLLUEURS (fid INTEGER PRIMARY KEY, geom BLOB, {COLUMNS})")
    database.executemany("INSERT INTO ETABLISSEMENTS_POLLUEURS (geom, identifiant, idetab, nom, codeape, cp, url_fiche) VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
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
        migration("0053_polluting_facilities").switch_to_database(connection)
    return refonte_database


@pytest.fixture
def client(database, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("les établissements pollueurs en base n'appellent aucun service")

    monkeypatch.setattr(sources.httpx, "get", no_network)
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def imported(database, path):
    with database.begin() as connection:
        return site_layers.import_sites(connection, site_layers.open_source(path, site_layers.table_columns(connection, LAYER), LAYER), LAYER)


def saint_lo_file(tmp_path):
    return write_geopackage(
        tmp_path / "etablissements.gpkg",
        [
            (point(*SAINT_LO), "0005303515", "6299", "UNITHER NORMANDY", "244C", "50200", fiche("6299")),
            (point(*SAINT_LO), "0005303515", "6299", "Doublon", "244C", "50200", fiche("6299")),
            (point(*SAINT_LO), None, "7000", "Sans identifiant", "244C", "50200", fiche("7000")),
            (None, "0005800419", "6433", "Sans géométrie", "2733Z", "27000", fiche("6433")),
        ],
    )


def test_the_facilities_are_keyed_by_their_irep_identifier_without_a_code_metier(database, tmp_path):
    assert imported(database, saint_lo_file(tmp_path)) == site_layers.ImportResult(imported={"point": 1}, skipped=3)

    with database.connect() as connection:
        rows = connection.execute(text("SELECT shape, identifiant, nom, codeape, cp, GeometryType(geometry), ST_SRID(geometry) FROM polluting_facilities")).all()
    assert [tuple(row) for row in rows] == [("point", "0005303515", "UNITHER NORMANDY", "244C", "50200", "POINT", 3857)]


def test_a_file_without_the_identifier_is_refused(database, tmp_path):
    path = tmp_path / "autre.gpkg"
    sqlite3.connect(path).execute("CREATE TABLE ETABLISSEMENTS_POLLUEURS (fid INTEGER, geom BLOB, code_metier TEXT)").connection.commit()

    with pytest.raises(site_layers.ImportRefused, match="identifiant"):
        imported(database, path)


def test_the_layer_is_served_as_vector_tiles_of_points_from_the_minimal_zoom(client, database, tmp_path):
    imported(database, saint_lo_file(tmp_path))

    layer = next(layer for layer in client.get("/layer-catalog").json()["layers"] if layer["code"] == CODE)
    assert (layer["kind"], layer["url"], layer["legendUrl"], layer["minZoom"]) == ("polluting-facilities", None, None, 9)
    assert layer["params"] == {"color": "#e08214", "outline": "#3f3f3f", "symbol": "point"}

    tile = client.get("/layer-catalog/{}/tiles/{}/{}/{}".format(CODE, *tile_of(*SAINT_LO, 12)))
    assert (tile.status_code, tile.headers["content-type"]) == (200, MVT)
    for content in (b"features", b"0005303515", b"UNITHER NORMANDY", b"codeape", b"details/6299"):
        assert content in tile.content

    below = client.get("/layer-catalog/{}/tiles/{}/{}/{}".format(CODE, *tile_of(*SAINT_LO, 8)))
    assert (below.status_code, below.content) == (200, b"")
