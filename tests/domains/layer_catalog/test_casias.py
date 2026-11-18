import importlib.util
import math
import sqlite3
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.auth import current_user
from app.domains.layer_catalog import casias, sources
from app.main import app

VERSIONS = Path(__file__).parents[3] / "migrations" / "versions"
POINTS = "fr-georisques-casias-points"
POLYGONS = "fr-georisques-casias-polygones"
MVT = "application/vnd.mapbox-vector-tile"
PARIS = (2.3522, 48.8566)
COLUMNS = "code_metier TEXT, nom_etablissement TEXT, etat_activite TEXT, fiche_risque TEXT, colonne_nouvelle TEXT"


def migration(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def geopackage(wkb, envelope=None):
    flags = 0b011 if envelope else 0b001
    header = b"GP\x00" + bytes([flags]) + struct.pack("<i", 4326)
    return header + (struct.pack("<dddd", *envelope) if envelope else b"") + wkb


def point(longitude, latitude):
    return geopackage(struct.pack("<BIdd", 1, 1, longitude, latitude))


def square(longitude, latitude, side=0.001):
    ring = [(longitude, latitude), (longitude + side, latitude), (longitude + side, latitude + side), (longitude, latitude + side), (longitude, latitude)]
    polygon = struct.pack("<BII", 1, 3, 1) + struct.pack("<I", len(ring)) + b"".join(struct.pack("<dd", *xy) for xy in ring)
    wkb = struct.pack("<BII", 1, 6, 1) + polygon
    return geopackage(wkb, (longitude, longitude + side, latitude, latitude + side))


def fiche(code):
    return f"https://fiches-risques.brgm.fr/georisques/casias/{code}"


def write_geopackage(path, points, polygons):
    database = sqlite3.connect(path)
    for table, rows in (("SSP_ETS_GE_POINT", points), ("SSP_ETS_GE_POLYGON", polygons)):
        database.execute(f"CREATE TABLE {table} (fid INTEGER PRIMARY KEY, geom BLOB, {COLUMNS})")
        database.executemany(f"INSERT INTO {table} (geom, code_metier, nom_etablissement, etat_activite, fiche_risque) VALUES (?, ?, ?, ?, ?)", rows)
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
        migration("0048_casias_sites").switch_to_database(connection)
    return refonte_database


@pytest.fixture
def client(database, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("les sites CASIAS en base n'appellent aucun service")

    monkeypatch.setattr(sources.httpx, "get", no_network)
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def imported(database, path):
    with database.begin() as connection:
        return casias.import_sites(connection, casias.open_source(path, casias.table_columns(connection)))


def paris_file(tmp_path):
    return write_geopackage(
        tmp_path / "casias.gpkg",
        [(point(*PARIS), "SSP000001", "Garage du centre", "En arrêt", fiche("SSP000001"))],
        [(square(*PARIS), "SSP000002", "Ancienne usine", "En activité", fiche("SSP000002"))],
    )


def test_the_wkb_is_read_after_the_geopackage_header_with_or_without_envelope():
    wkb = struct.pack("<BIdd", 1, 1, *PARIS)
    assert casias.wkb_of(geopackage(wkb)) == wkb
    assert casias.wkb_of(geopackage(wkb, (*PARIS, *PARIS))) == wkb
    assert casias.wkb_of(b"GP\x00\x11" + struct.pack("<i", 4326) + wkb) is None
    assert casias.wkb_of(b"not a geometry") is None
    assert casias.wkb_of(None) is None


def test_the_import_replaces_the_points_and_the_footprints_and_skips_the_unusable_rows(database, tmp_path):
    path = write_geopackage(
        tmp_path / "casias.gpkg",
        [
            (point(*PARIS), "SSP000001", "Garage", "En arrêt", fiche("SSP000001")),
            (point(-61.5, 16.2), "SSP000003", "Station", " ", fiche("SSP000003")),
            (point(*PARIS), "SSP000001", "Doublon", "En arrêt", fiche("SSP000001")),
            (None, "SSP000004", "Sans géométrie", "En arrêt", fiche("SSP000004")),
            (point(*PARIS), None, "Sans code", "En arrêt", None),
        ],
        [(square(*PARIS), "SSP000001", "Garage", "En arrêt", fiche("SSP000001"))],
    )

    assert imported(database, path) == casias.ImportResult(imported={"point": 2, "polygon": 1}, skipped=3)
    assert imported(database, path) == casias.ImportResult(imported={"point": 2, "polygon": 1}, skipped=3)

    with database.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT shape, code_metier, etat_activite, adresse, GeometryType(geometry), ST_SRID(geometry), "
                "round(ST_XMin(ST_Transform(geometry, 4326))::numeric, 4)::float8 FROM casias_sites ORDER BY shape, code_metier"
            )
        ).all()
    assert [tuple(row) for row in rows] == [
        ("point", "SSP000001", "En arrêt", None, "POINT", 3857, 2.3522),
        ("point", "SSP000003", None, None, "POINT", 3857, -61.5),
        ("polygon", "SSP000001", "En arrêt", None, "MULTIPOLYGON", 3857, 2.3522),
    ]


def test_every_column_of_the_table_is_read_from_the_file_when_it_has_it(database, tmp_path):
    with database.connect() as connection:
        found = casias.open_source(paris_file(tmp_path), casias.table_columns(connection))

    points = found.tables[0]
    assert (points.shape, points.columns) == ("point", ("code_metier", "nom_etablissement", "etat_activite", "fiche_risque"))
    assert points.ignored == ("colonne_nouvelle",)
    assert "adresse" in points.missing and "geometry" not in points.missing and len(points.missing) == 18


def test_a_file_without_one_of_the_casias_tables_is_refused(database, tmp_path):
    path = tmp_path / "autre.gpkg"
    sqlite3.connect(path).execute("CREATE TABLE SSP_ETS_GE_POINT (fid INTEGER, geom BLOB, code_metier TEXT)").connection.commit()

    with pytest.raises(casias.ImportRefused, match="SSP_ETS_GE_POLYGON"):
        imported(database, path)


def test_each_layer_is_served_as_vector_tiles_of_its_own_shape(client, database, tmp_path):
    imported(database, paris_file(tmp_path))

    layers = {layer["code"]: layer for layer in client.get("/layer-catalog").json()["layers"]}
    assert (layers[POINTS]["kind"], layers[POINTS]["url"], layers[POINTS]["legendUrl"]) == ("casias", None, None)
    assert layers[POINTS]["params"] == {"color": "#4884cc", "outline": "#3f3f3f", "symbol": "point"}
    assert (layers[POLYGONS]["kind"], layers[POLYGONS]["params"]) == ("casias", {"color": "#4884cc"})

    z, x, y = tile_of(*PARIS, 14)
    points = client.get(f"/layer-catalog/{POINTS}/tiles/{z}/{x}/{y}")
    assert (points.status_code, points.headers["content-type"]) == (200, MVT)
    for content in (b"features", b"SSP000001", b"Garage du centre", b"url_fiche", b"casias/SSP000001", b"etat_activite"):
        assert content in points.content
    assert b"SSP000002" not in points.content

    polygons = client.get(f"/layer-catalog/{POLYGONS}/tiles/{z}/{x}/{y}")
    assert (polygons.status_code, polygons.headers["content-type"]) == (200, MVT)
    assert b"SSP000002" in polygons.content and b"SSP000001" not in polygons.content

    elsewhere = client.get(f"/layer-catalog/{POINTS}/tiles/14/0/0")
    assert (elsewhere.status_code, elsewhere.content) == (200, b"")


def test_below_the_minimal_zoom_of_each_layer_the_tile_is_empty(client, database, tmp_path):
    imported(database, paris_file(tmp_path))

    points = client.get("/layer-catalog/{}/tiles/{}/{}/{}".format(POINTS, *tile_of(*PARIS, 12)))
    polygons = client.get("/layer-catalog/{}/tiles/{}/{}/{}".format(POLYGONS, *tile_of(*PARIS, 12)))

    assert (points.status_code, points.content) == (200, b"")
    assert polygons.status_code == 200 and b"SSP000002" in polygons.content
