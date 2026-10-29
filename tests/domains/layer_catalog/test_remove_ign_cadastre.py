import importlib.util
import json
import uuid
from pathlib import Path

from sqlalchemy import text

from tests.domains.profile.test_routes import OTHER, call, client  # noqa: F401

VERSIONS = Path(__file__).parents[3] / "migrations" / "versions"


def migration(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def investigation_with(engine, layer_ids):
    content = json.dumps({"coordinates": {"lat": 43.6, "lng": 1.4}, "maps": {"layers": {"topographicMap": [{"id": layer_id} for layer_id in layer_ids]}}})
    with engine.begin() as connection:
        page_id = connection.execute(
            text("INSERT INTO saved_pages (uuid, data, project_ref) VALUES (:uuid, :data, '63GT.24.0048') RETURNING id"),
            {"uuid": str(uuid.uuid4()), "data": content},
        ).scalar_one()
        connection.execute(
            text("INSERT INTO saved_page_versions (id, saved_page_id, version, data) VALUES (:id, :page_id, 1, :data)"),
            {"id": str(uuid.uuid4()), "page_id": page_id, "data": content},
        )
    return page_id


def stored_layer_ids(engine, page_id):
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT data FROM saved_pages WHERE id = :id "
                "UNION ALL SELECT data FROM saved_page_versions WHERE saved_page_id = :id"
            ),
            {"id": page_id},
        ).scalars()
        return [[layer["id"] for layer in json.loads(data)["maps"]["layers"]["topographicMap"]] for data in rows]


def remove_ign_cadastre(engine):
    with engine.begin() as connection:
        migration("0013_remove_ign_cadastre").remove(connection)


def test_only_the_etalab_cadastre_remains_for_france(client, refonte_database):
    with refonte_database.begin() as connection:
        for name in ("0007_layer_catalog", "0008_layer_catalog_france"):
            migration(name).seed(connection)

    remove_ign_cadastre(refonte_database)

    codes = [layer["code"] for layer in client.get("/layer-catalog").json()["layers"]]
    assert "fr-cadastre" not in codes
    assert "fr-cadastre-etalab" in codes


def test_favorites_and_my_layers_lose_the_ign_cadastre_only(client, refonte_database):
    call(client, "PATCH", "/me/preferences", {"mapLayers": [
        {"layerId": "fr-geologie", "visible": True, "opacity": 1},
        {"layerId": "fr-cadastre", "visible": True, "opacity": 0.6},
        {"layerId": "fr-cadastre-etalab", "visible": False, "opacity": 1},
    ]})
    call(client, "PUT", "/me/favorites/layers/fr-cadastre")
    call(client, "PUT", "/me/favorites/layers/fr-cadastre-etalab")
    call(client, "PATCH", "/me/preferences", {"mapLayers": [{"layerId": "fr-cadastre", "visible": True, "opacity": 1}]}, identity=OTHER)

    remove_ign_cadastre(refonte_database)

    assert call(client, "GET", "/me/favorites").json()["layers"] == ["fr-cadastre-etalab"]
    assert call(client, "GET", "/me/preferences").json()["mapLayers"] == [
        {"layerId": "fr-geologie", "visible": True, "opacity": 1.0},
        {"layerId": "fr-cadastre-etalab", "visible": False, "opacity": 1.0},
    ]
    assert call(client, "GET", "/me/preferences", identity=OTHER).json()["mapLayers"] == []


def test_saved_investigations_show_the_etalab_cadastre_instead(client, refonte_database):
    page_id = investigation_with(refonte_database, ["fr-cadastre", "fr-cadastre-etalab", "fr-geologie"])

    remove_ign_cadastre(refonte_database)

    assert stored_layer_ids(refonte_database, page_id) == [["fr-cadastre-etalab", "fr-cadastre-etalab", "fr-geologie"]] * 2
