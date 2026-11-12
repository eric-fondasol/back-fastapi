import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.auth import current_user
from app.domains.layer_catalog import imports, sources
from app.main import app

VERSIONS = Path(__file__).parents[3] / "migrations" / "versions"
MONTREAL = "-73.7,45.45,-73.5,45.6"
WEBP = b"RIFF\x00\x00\x00\x00WEBPtuile"
PNG = b"\x89PNG\r\n\x1a\nlegende"
GROUNDWATER = "ca-qc-aires-protection-eau-souterraine"
CONTOURS = "ca-mtl-isopiezes"
ROCK_DEPTH = "ca-mtl-profondeur-roc-1427"


def migration(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def square(west, south, side):
    ring = [[west, south], [west + side, south], [west + side, south + side], [west, south + side], [west, south]]
    return {"type": "Polygon", "coordinates": [ring]}


def feature(geometry, **properties):
    return {"type": "Feature", "geometry": geometry, "properties": properties}


@pytest.fixture
def database(refonte_database):
    with refonte_database.begin() as connection:
        migration("0007_layer_catalog").seed(connection)
        migration("0008_layer_catalog_france").seed(connection)
        migration("0038_catalog_database_layers").seed(connection)
    return refonte_database


@pytest.fixture
def client(database, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("une couche en base n'appelle aucun service")

    monkeypatch.setattr(sources.httpx, "get", no_network)
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def catalog_layers(client):
    return {layer["code"]: layer for layer in client.get("/layer-catalog").json()["layers"]}


def test_the_seven_stored_layers_are_in_the_canadian_catalog_without_address(client):
    layers = catalog_layers(client)

    stored = {code: layer["kind"] for code, layer in layers.items() if layer["kind"] in ("database", "database-tiles")}

    assert stored == {
        "ca-qc-aires-protection-eau-souterraine": "database",
        "ca-qc-aires-protection-eau-surface": "database",
        "ca-mtl-depots-meubles-1426-polygones": "database",
        "ca-mtl-depots-meubles-1426": "database-tiles",
        "ca-mtl-profondeur-roc-1427": "database-tiles",
        "ca-mtl-carte-hydrogeologique": "database-tiles",
        "ca-mtl-isopiezes": "database",
    }
    assert {layers[code]["country"] for code in stored} == {"ca"}
    assert {layers[code]["url"] for code in stored} == {None}
    assert layers[GROUNDWATER]["params"]["classes"]["property"] == "Nom_AP"
    assert layers[CONTOURS]["params"]["labelField"] == "Élévation de la nappe (m)"
    assert layers[ROCK_DEPTH]["storedLegend"] is False


def test_a_stored_layer_without_address_is_accepted_and_another_kind_without_address_is_refused(database):
    with database.connect() as connection:
        with pytest.raises(Exception, match="catalog_layers_url_check"):
            connection.execute(text("UPDATE catalog_layers SET url = NULL WHERE code = 'fr-geologie'"))
    with database.connect() as connection:
        with pytest.raises(Exception, match="catalog_layers_url_check"):
            connection.execute(text(f"UPDATE catalog_layers SET url = 'https://exemple.fr' WHERE code = '{GROUNDWATER}'"))


def test_the_objects_of_a_stored_layer_are_read_in_the_database_and_clipped_to_the_view(client, database):
    with database.begin() as connection:
        imports.import_features(
            connection,
            GROUNDWATER,
            {
                "type": "FeatureCollection",
                "features": [
                    feature(square(-73.62, 45.5, 0.01), Nom_AP=1, Nom_SP="Puits de Montréal"),
                    feature(square(-73.75, 45.5, 0.1), Nom_AP=4),
                    feature(square(-71.3, 46.8, 0.01), Nom_AP=2),
                ],
            },
        )

    response = client.get(f"/layer-catalog/{GROUNDWATER}/features", params={"bbox": MONTREAL, "zoom": 12})

    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is False
    assert sorted(item["properties"]["Nom_AP"] for item in body["features"]) == [1, 4]
    clipped = next(item for item in body["features"] if item["properties"]["Nom_AP"] == 4)
    assert min(position[0] for position in clipped["geometry"]["coordinates"][0]) == pytest.approx(-73.7)


def test_below_the_minimal_zoom_a_stored_layer_reads_nothing(client, database):
    with database.begin() as connection:
        imports.import_features(connection, GROUNDWATER, {"type": "FeatureCollection", "features": [feature(square(-73.62, 45.5, 0.01), Nom_AP=1)]})

    body = client.get(f"/layer-catalog/{GROUNDWATER}/features", params={"bbox": MONTREAL, "zoom": 9}).json()

    assert body["features"] == []


def test_a_new_import_replaces_the_objects_of_the_layer(client, database):
    lines = {"type": "MultiLineString", "coordinates": [[[-73.65, 45.5], [-73.55, 45.55]]]}
    with database.begin() as connection:
        imports.import_features(connection, CONTOURS, {"type": "FeatureCollection", "features": [feature(lines, elevation="15,25")]})
        count = imports.import_features(connection, CONTOURS, {"type": "FeatureCollection", "features": [feature(lines, elevation="22,875")]})

    body = client.get(f"/layer-catalog/{CONTOURS}/features", params={"bbox": MONTREAL, "zoom": 12}).json()

    assert count == 1
    assert [item["properties"] for item in body["features"]] == [{"elevation": "22,875"}]


def test_objects_are_refused_for_a_layer_that_is_not_stored_as_objects(database):
    with database.begin() as connection, pytest.raises(imports.ImportRefused, match="database-tiles"):
        imports.import_features(connection, ROCK_DEPTH, {"type": "FeatureCollection", "features": []})


def write_tile(folder, z, x, y, content=WEBP):
    path = folder / str(z) / str(x) / f"{y}.webp"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_a_stored_tile_is_read_in_the_database_and_a_missing_one_is_a_404(client, database, tmp_path):
    write_tile(tmp_path, 12, 1209, 1465)
    write_tile(tmp_path, 12, 1210, 1465)
    (tmp_path / "12" / "1209" / "notes.txt").write_text("ignoré")
    with database.begin() as connection:
        count = imports.import_tiles(connection, ROCK_DEPTH, tmp_path)

    found = client.get(f"/layer-catalog/{ROCK_DEPTH}/tiles/12/1209/1465")
    missing = client.get(f"/layer-catalog/{ROCK_DEPTH}/tiles/12/1300/1465")

    assert count == 2
    assert found.status_code == 200
    assert found.content == WEBP
    assert found.headers["content-type"] == "image/webp"
    assert found.headers["cache-control"] == "private, max-age=86400"
    assert missing.status_code == 404


def test_tiles_are_refused_for_an_empty_folder(database, tmp_path):
    with database.begin() as connection, pytest.raises(imports.ImportRefused, match="Aucune tuile"):
        imports.import_tiles(connection, ROCK_DEPTH, tmp_path)


def test_a_stored_legend_is_served_and_announced_in_the_catalog(client, database):
    assert client.get(f"/layer-catalog/{ROCK_DEPTH}/legend").status_code == 404

    with database.begin() as connection:
        imports.import_legend(connection, ROCK_DEPTH, PNG, "image/png")

    response = client.get(f"/layer-catalog/{ROCK_DEPTH}/legend")

    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"
    assert catalog_layers(client)[ROCK_DEPTH]["storedLegend"] is True


def test_the_command_line_imports_a_geojson_file(database, tmp_path):
    collection = {"type": "FeatureCollection", "features": [feature(square(-73.62, 45.5, 0.01), Nom_AP=2)]}
    source = tmp_path / "aires.geojson"
    source.write_text(json.dumps(collection), encoding="utf-8")

    assert imports.main(["features", GROUNDWATER, str(source)]) == 0
    assert imports.main(["features", "inconnue", str(source)]) == 1

    with database.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM catalog_layer_features")).scalar() == 1


def test_a_disabled_stored_layer_has_neither_objects_nor_tiles(client, database, tmp_path):
    write_tile(tmp_path, 12, 1209, 1465)
    with database.begin() as connection:
        imports.import_tiles(connection, ROCK_DEPTH, tmp_path)
        connection.execute(text("UPDATE catalog_layers SET enabled = false WHERE code IN (:rock, :water)"), {"rock": ROCK_DEPTH, "water": GROUNDWATER})

    assert client.get(f"/layer-catalog/{ROCK_DEPTH}/tiles/12/1209/1465").status_code == 404
    assert client.get(f"/layer-catalog/{GROUNDWATER}/features", params={"bbox": MONTREAL, "zoom": 12}).status_code == 404


def test_the_relayed_tiles_still_ask_their_service(client, database, monkeypatch):
    calls = []

    def get(url, params, timeout, follow_redirects):
        calls.append(url)
        return httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(sources.httpx, "get", get)
    with database.begin() as connection:
        migration("0034_layer_catalog_canada").seed(connection)
        migration("0036_relay_foret_ouverte_layers").relay(connection)

    assert client.get("/layer-catalog/ca-qc-mrnf-hydro-surfacique-lidar/tiles/15/9687/11720").status_code == 200
    assert calls == ["https://geoegl.msp.gouv.qc.ca/ws/mffpecofor.fcgi"]
