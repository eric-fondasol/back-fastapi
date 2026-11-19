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
from app.domains.layer_catalog.icpe import LAYER
from app.main import app

VERSIONS = Path(__file__).parents[3] / "migrations" / "versions"
CODE = "fr-georisques-icpe"
MVT = "application/vnd.mapbox-vector-tile"
EPERNAY = (3.9548, 49.0402)
COLUMNS = "code_aiot TEXT, raison_sociale TEXT, commune TEXT, activite_principale TEXT, seveso TEXT, regime_vig TEXT, legende TEXT, url_fiche TEXT"


def migration(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def point(longitude, latitude):
    return b"GP\x00\x01" + struct.pack("<i", 4326) + struct.pack("<BIdd", 1, 1, longitude, latitude)


def fiche(code):
    return f"https://www.georisques.gouv.fr/risques/installations/donnees/details/{code}"


def write_geopackage(path, rows):
    database = sqlite3.connect(path)
    database.execute(f"CREATE TABLE INSTALLATIONS_CLASSEES_SIMPLIFIE_GE (fid INTEGER PRIMARY KEY, geom BLOB, {COLUMNS})")
    database.executemany(
        "INSERT INTO INSTALLATIONS_CLASSEES_SIMPLIFIE_GE (geom, code_aiot, raison_sociale, commune, activite_principale, seveso, regime_vig, legende, url_fiche) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        migration("0055_icpe_sites").switch_to_database(connection)
        migration("0056_icpe_icons").switch_to_icons(connection)
    return refonte_database


@pytest.fixture
def client(database, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("les installations classées en base n'appellent aucun service")

    monkeypatch.setattr(sources.httpx, "get", no_network)
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def imported(database, path):
    with database.begin() as connection:
        return site_layers.import_sites(connection, site_layers.open_source(path, site_layers.table_columns(connection, LAYER), LAYER), LAYER)


def epernay_file(tmp_path):
    return write_geopackage(
        tmp_path / "icpe.gpkg",
        [
            (point(*EPERNAY), "0005704438", "Champagne Moët", "Épernay", "11 - Fabrication de boissons", "Seveso seuil bas", "Autorisation", "Usine Seveso", fiche("0005704438")),
            (point(*EPERNAY), "0005704438", "Doublon", "Épernay", None, None, None, "Autres", fiche("0005704438")),
            (point(*EPERNAY), None, "Sans code AIOT", "Épernay", None, None, None, "Autres", None),
            (None, "0005704805", "Sans géométrie", "Œuilly", None, None, None, "Autres", fiche("0005704805")),
        ],
    )


def test_the_installations_are_keyed_by_their_aiot_code(database, tmp_path):
    assert imported(database, epernay_file(tmp_path)) == site_layers.ImportResult(imported={"point": 1}, skipped=3)

    with database.connect() as connection:
        rows = connection.execute(text("SELECT shape, code_aiot, raison_sociale, seveso, legende, GeometryType(geometry), ST_SRID(geometry) FROM icpe_sites")).all()
    assert [tuple(row) for row in rows] == [("point", "0005704438", "Champagne Moët", "Seveso seuil bas", "Usine Seveso", "POINT", 3857)]


def test_a_file_without_the_aiot_code_is_refused(database, tmp_path):
    path = tmp_path / "autre.gpkg"
    sqlite3.connect(path).execute("CREATE TABLE INSTALLATIONS_CLASSEES_SIMPLIFIE_GE (fid INTEGER, geom BLOB, code_metier TEXT)").connection.commit()

    with pytest.raises(site_layers.ImportRefused, match="code_aiot"):
        imported(database, path)


def test_the_layer_is_served_as_vector_tiles_of_points_coloured_by_category_from_the_minimal_zoom(client, database, tmp_path):
    imported(database, epernay_file(tmp_path))

    layer = next(layer for layer in client.get("/layer-catalog").json()["layers"] if layer["code"] == CODE)
    assert (layer["kind"], layer["url"], layer["legendUrl"], layer["minZoom"]) == ("icpe", None, None, 11)
    assert layer["params"]["classes"]["property"] == "legende"
    assert {entry["value"]: entry.get("icon") for entry in layer["params"]["classes"]["values"]} == {
        "Usine Seveso": "sevesoPlant",
        "Usine non Seveso": "plant",
        "Carrière": "quarry",
        "Eolienne": "windTurbine",
        "Elevage de porc": "pig",
        "Elevage de volaille": "poultry",
        "Elevage de bovin": "cattle",
        "Autres": None,
    }

    tile = client.get("/layer-catalog/{}/tiles/{}/{}/{}".format(CODE, *tile_of(*EPERNAY, 14)))
    assert (tile.status_code, tile.headers["content-type"]) == (200, MVT)
    for content in (b"features", b"0005704438", "Champagne Moët".encode(), b"Usine Seveso", b"regime_vig", b"details/0005704438"):
        assert content in tile.content

    below = client.get("/layer-catalog/{}/tiles/{}/{}/{}".format(CODE, *tile_of(*EPERNAY, 10)))
    assert (below.status_code, below.content) == (200, b"")
