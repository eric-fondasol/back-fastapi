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
from app.domains.layer_catalog.basol import LAYER
from app.main import app

VERSIONS = Path(__file__).parents[3] / "migrations" / "versions"
POINTS = "fr-georisques-pollution-instruction-points"
POLYGONS = "fr-georisques-pollution-instruction-polygones"
CASIAS_POINTS = "fr-georisques-casias-points"
MVT = "application/vnd.mapbox-vector-tile"
LYON = (4.8357, 45.764)
COLUMNS = "id TEXT, code_metier TEXT, nom_etablissement TEXT, nom_commune TEXT, statut_instruction TEXT, description TEXT, url_fiche TEXT"


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
    return f"https://fiches-risques.brgm.fr/georisques/infosols/instruction/{code}"


def write_geopackage(path, points, polygons):
    database = sqlite3.connect(path)
    for table, rows in (("SSP_INSTR_GE_POINT", points), ("SSP_INSTR_GE_POLYGONE", polygons)):
        database.execute(f"CREATE TABLE {table} (fid INTEGER PRIMARY KEY, geom BLOB, {COLUMNS})")
        database.executemany(
            f"INSERT INTO {table} (geom, id, code_metier, nom_etablissement, nom_commune, statut_instruction, description, url_fiche) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
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
        migration("0048_casias_sites").switch_to_database(connection)
        migration("0051_basol_sites").switch_to_database(connection)
    return refonte_database


@pytest.fixture
def client(database, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("les sites BASOL en base n'appellent aucun service")

    monkeypatch.setattr(sources.httpx, "get", no_network)
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def imported(database, path):
    with database.begin() as connection:
        return site_layers.import_sites(connection, site_layers.open_source(path, site_layers.table_columns(connection, LAYER), LAYER), LAYER)


def lyon_file(tmp_path):
    return write_geopackage(
        tmp_path / "basol.gpkg",
        [(point(*LYON), "1", "SSP000001", "Ancienne usine à gaz", "LYON", "En cours", "Longue description", fiche("SSP000001"))],
        [(square(*LYON), "2", "SSP000002", "Ancienne décharge", "LYON", "Clôturée", None, fiche("SSP000002"))],
    )


def test_a_site_repeated_on_several_towns_keeps_its_first_row_and_the_unusable_rows_are_skipped(database, tmp_path):
    path = write_geopackage(
        tmp_path / "basol.gpkg",
        [
            (point(*LYON), "10", "SSP000001", "Crassiers", "VILLEURBANNE", "En cours", None, fiche("SSP000001")),
            (point(*LYON), "11", "SSP000001", "Crassiers", "LYON", "En cours", None, fiche("SSP000001")),
            (point(55.45, -20.88), "12", "SSP000003", "Dépôt", "SAINT-DENIS", "Clôturée", "", fiche("SSP000003")),
            (None, "13", "SSP000004", "Sans géométrie", "LYON", "En cours", None, fiche("SSP000004")),
        ],
        [(square(*LYON), "10", "SSP000001", "Crassiers", "VILLEURBANNE", "En cours", None, fiche("SSP000001"))],
    )

    assert imported(database, path) == site_layers.ImportResult(imported={"point": 2, "polygon": 1}, skipped=2)
    assert imported(database, path) == site_layers.ImportResult(imported={"point": 2, "polygon": 1}, skipped=2)

    with database.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT shape, code_metier, id, nom_commune, description, GeometryType(geometry), ST_SRID(geometry), "
                "round(ST_XMin(ST_Transform(geometry, 4326))::numeric, 4)::float8 FROM basol_sites ORDER BY shape, code_metier"
            )
        ).all()
    assert [tuple(row) for row in rows] == [
        ("point", "SSP000001", "10", "VILLEURBANNE", None, "POINT", 3857, 4.8357),
        ("point", "SSP000003", "12", "SAINT-DENIS", None, "POINT", 3857, 55.45),
        ("polygon", "SSP000001", "10", "VILLEURBANNE", None, "MULTIPOLYGON", 3857, 4.8357),
    ]


def test_every_column_of_the_table_is_read_from_the_file_when_it_has_it(database, tmp_path):
    with database.connect() as connection:
        found = site_layers.open_source(lyon_file(tmp_path), site_layers.table_columns(connection, LAYER), LAYER)

    points = found.tables[0]
    assert (points.shape, points.columns) == (
        "point",
        ("id", "code_metier", "description", "nom_etablissement", "nom_commune", "statut_instruction", "url_fiche"),
    )
    assert points.ignored == ()
    assert "polygone_wgs84" in points.missing and len(points.missing) == 17


def test_a_file_without_one_of_the_basol_tables_is_refused(database, tmp_path):
    path = tmp_path / "autre.gpkg"
    sqlite3.connect(path).execute("CREATE TABLE SSP_INSTR_GE_POINT (fid INTEGER, geom BLOB, code_metier TEXT)").connection.commit()

    with pytest.raises(site_layers.ImportRefused, match="SSP_INSTR_GE_POLYGONE"):
        imported(database, path)


def test_each_layer_is_served_as_vector_tiles_of_its_own_shape_without_the_description(client, database, tmp_path):
    imported(database, lyon_file(tmp_path))

    layers = {layer["code"]: layer for layer in client.get("/layer-catalog").json()["layers"]}
    assert (layers[POINTS]["kind"], layers[POINTS]["url"], layers[POINTS]["legendUrl"]) == ("basol", None, None)
    assert layers[POINTS]["params"] == {"color": "#d7301f", "outline": "#3f3f3f", "symbol": "point"}
    assert (layers[POLYGONS]["kind"], layers[POLYGONS]["params"]) == ("basol", {"color": "#d7301f"})

    z, x, y = tile_of(*LYON, 14)
    points = client.get(f"/layer-catalog/{POINTS}/tiles/{z}/{x}/{y}")
    assert (points.status_code, points.headers["content-type"]) == (200, MVT)
    for content in (b"features", b"SSP000001", "Ancienne usine à gaz".encode(), b"statut_instruction", b"En cours", b"instruction/SSP000001"):
        assert content in points.content
    assert b"SSP000002" not in points.content and b"Longue description" not in points.content

    polygons = client.get(f"/layer-catalog/{POLYGONS}/tiles/{z}/{x}/{y}")
    assert (polygons.status_code, polygons.headers["content-type"]) == (200, MVT)
    assert b"SSP000002" in polygons.content and b"SSP000001" not in polygons.content

    casias = client.get(f"/layer-catalog/{CASIAS_POINTS}/tiles/{z}/{x}/{y}")
    assert (casias.status_code, casias.content) == (200, b"")


def test_below_the_minimal_zoom_the_tile_is_empty(client, database, tmp_path):
    imported(database, lyon_file(tmp_path))

    below = client.get("/layer-catalog/{}/tiles/{}/{}/{}".format(POINTS, *tile_of(*LYON, 11)))
    at = client.get("/layer-catalog/{}/tiles/{}/{}/{}".format(POINTS, *tile_of(*LYON, 12)))

    assert (below.status_code, below.content) == (200, b"")
    assert at.status_code == 200 and b"SSP000001" in at.content
