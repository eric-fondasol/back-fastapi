import importlib.util
import math
import sqlite3
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.auth import current_user
from app.domains.layer_catalog import bss, sources
from app.main import app

VERSIONS = Path(__file__).parents[3] / "migrations" / "versions"
CODE = "fr-brgm-bss-tous-ouvrages"
MVT = "application/vnd.mapbox-vector-tile"
PARIS = (2.3522, 48.8566)


def migration(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def geopackage_point(longitude, latitude, envelope=False):
    flags = 0b011 if envelope else 0b001
    header = b"GP\x00" + bytes([flags]) + struct.pack("<i", 4326)
    box = struct.pack("<dddd", longitude, longitude, latitude, latitude) if envelope else b""
    return header + box + struct.pack("<BIdd", 1, 1, longitude, latitude)


def link(reference):
    return f'"=LIEN_HYPERTEXTE(""http://ficheinfoterre.brgm.fr/InfoterreFiche/ficheBss.action?id={reference}"" ;""x"")"'


def write_geopackage(path, rows):
    database = sqlite3.connect(path)
    database.execute(
        "CREATE TABLE BSS_TOTAL (fid INTEGER PRIMARY KEY, geom BLOB, bss_id TEXT, reference TEXT, code_log TEXT, lien TEXT, "
        "z_bdalti TEXT, prof_eau_sol TEXT, longitude TEXT, colonne_nouvelle TEXT)"
    )
    database.executemany(
        "INSERT INTO BSS_TOTAL (geom, bss_id, reference, code_log, lien, z_bdalti, prof_eau_sol, longitude) VALUES (?, ?, ?, ?, ?, '99', ' ', '2,35')",
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
        migration("0047_bss_wells").switch_to_database(connection)
    return refonte_database


@pytest.fixture
def client(database, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("les ouvrages BSS en base n'appellent aucun service")

    monkeypatch.setattr(sources.httpx, "get", no_network)
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def source(database, path):
    with database.connect() as connection:
        return bss.open_source(path, bss.table_columns(connection))


def imported(database, path):
    with database.begin() as connection:
        return bss.import_wells(connection, bss.open_source(path, bss.table_columns(connection)))


def test_a_geopackage_point_is_read_with_or_without_envelope():
    assert bss.point_of(geopackage_point(*PARIS)) == PARIS
    assert bss.point_of(geopackage_point(*PARIS, envelope=True)) == PARIS
    assert bss.point_of(b"not a geometry") is None
    assert bss.point_of(None) is None


def test_the_sheet_url_comes_from_the_excel_formula_with_its_spaces_encoded():
    assert bss.sheet_url_of(link("01574X0006/SO")) == "http://ficheinfoterre.brgm.fr/InfoterreFiche/ficheBss.action?id=01574X0006/SO"
    assert bss.sheet_url_of(link("01705X0006/92 FE")) == "http://ficheinfoterre.brgm.fr/InfoterreFiche/ficheBss.action?id=01705X0006/92%20FE"
    assert bss.sheet_url_of("sans lien") is None


def test_the_import_replaces_the_wells_and_skips_the_unusable_rows(database, tmp_path):
    path = write_geopackage(
        tmp_path / "bss.gpkg",
        [
            (geopackage_point(*PARIS), "BSS000PARI", "01834X0001/F", "5", link("01834X0001/F")),
            (geopackage_point(-61.5, 16.2), "BSS000GUAD", "01171X0001/P", "1", link("01171X0001/P")),
            (geopackage_point(*PARIS), "BSS000SANS", "01834X0002/F", "9", link("01834X0002/F")),
            (None, "BSS000VIDE", "01834X0003/F", "2", link("01834X0003/F")),
        ],
    )

    assert imported(database, path) == bss.ImportResult(imported=2, skipped=2)
    assert imported(database, path) == bss.ImportResult(imported=2, skipped=2)

    with database.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT bss_id, code_log, z_bdalti, prof_eau_sol, nature, round(ST_X(ST_Transform(geometry, 4326))::numeric, 4)::float8 "
                "FROM bss_wells ORDER BY bss_id"
            )
        ).all()
    assert [tuple(row) for row in rows] == [("BSS000GUAD", "1", "99", None, None, -61.5), ("BSS000PARI", "5", "99", None, None, 2.3522)]


def test_every_column_of_the_table_is_read_from_the_file_when_it_has_it(database, tmp_path):
    found = source(database, write_geopackage(tmp_path / "bss.gpkg", []))

    assert found.columns == ("reference", "bss_id", "longitude", "prof_eau_sol", "code_log", "lien", "z_bdalti")
    assert found.ignored == ("colonne_nouvelle",)
    assert "nature" in found.missing and "sheet_url" not in found.missing and len(found.missing) == 130


def test_a_file_without_the_bss_columns_is_refused(database, tmp_path):
    path = tmp_path / "autre.gpkg"
    sqlite3.connect(path).execute("CREATE TABLE BSS_TOTAL (fid INTEGER, geom BLOB)").connection.commit()

    with pytest.raises(bss.ImportRefused, match="bss_id"):
        imported(database, path)


def test_the_layer_is_served_as_vector_tiles_with_its_classes_and_no_address(client, database, tmp_path):
    imported(database, write_geopackage(tmp_path / "bss.gpkg", [(geopackage_point(*PARIS), "BSS000PARI", "01834X0001/F", "3", link("01834X0001/F"))]))

    layer = {layer["code"]: layer for layer in client.get("/layer-catalog").json()["layers"]}[CODE]
    assert (layer["kind"], layer["url"], layer["legendUrl"]) == ("bss", None, None)
    assert (layer["params"]["symbol"], layer["params"]["classes"]["property"]) == ("point", "code_log")
    assert [(value["value"], value["dot"]) for value in layer["params"]["classes"]["values"]] == [
        ("1", True),
        ("2", False),
        ("3", True),
        ("4", False),
        ("5", True),
        ("6", False),
    ]

    z, x, y = tile_of(*PARIS, 14)
    response = client.get(f"/layer-catalog/{CODE}/tiles/{z}/{x}/{y}")
    assert response.status_code == 200
    assert response.headers["content-type"] == MVT
    for content in (b"features", b"BSS000PARI", b"url_fiche", b"ficheBss.action?id=01834X0001/F", b"code_log", b"z_bdalti", b"99"):
        assert content in response.content

    elsewhere = client.get(f"/layer-catalog/{CODE}/tiles/14/0/0")
    assert (elsewhere.status_code, elsewhere.content) == (200, b"")


def test_below_the_minimal_zoom_the_tile_is_empty(client, database, tmp_path):
    imported(database, write_geopackage(tmp_path / "bss.gpkg", [(geopackage_point(*PARIS), "BSS000PARI", "01834X0001/F", "3", link("01834X0001/F"))]))

    z, x, y = tile_of(*PARIS, 8)
    response = client.get(f"/layer-catalog/{CODE}/tiles/{z}/{x}/{y}")

    assert (response.status_code, response.content) == (200, b"")

