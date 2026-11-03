import importlib.util
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

VERSIONS = Path(__file__).parents[2] / "migrations" / "versions"


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


SPIKE = "6f1c2a3e-0b1d-4c55-9a77-1f2e3d4c5b6a"
OTHER = "7a2d3b4f-1c2e-4d66-8b88-2a3f4e5d6c7b"


# La migration touche saved_pages.data, retirée par 0018 : elle se vérifie sur le schéma de 0012.
@pytest.fixture
def before_0013(schema_at):
    return schema_at("0012")


def remove_ign_cadastre(database):
    with database.begin() as connection:
        migration("0013_remove_ign_cadastre").remove(connection)


def run(database, statement, **parameters):
    with database.begin() as connection:
        connection.execute(text(statement), parameters)


def values(database, query, **parameters):
    with database.connect() as connection:
        return list(connection.execute(text(query), parameters).scalars())


def layers(entries):
    return json.dumps([{"layer_id": layer_id, "visible": visible, "opacity": 1} for layer_id, visible in entries])


def test_only_the_etalab_cadastre_remains_for_france(before_0013):
    with before_0013.begin() as connection:
        for name in ("0007_layer_catalog", "0008_layer_catalog_france"):
            migration(name).seed(connection)

    remove_ign_cadastre(before_0013)

    codes = values(before_0013, "SELECT code FROM catalog_layers")
    assert "fr-cadastre" not in codes
    assert "fr-cadastre-etalab" in codes


def test_favorites_and_my_layers_lose_the_ign_cadastre_only(before_0013):
    for user_id, email in ((SPIKE, "spike@fondasol.fr"), (OTHER, "autre@fondasol.fr")):
        run(before_0013, "INSERT INTO users (id, email, created_at) VALUES (:id, :email, now())", id=user_id, email=email)
    run(
        before_0013,
        "INSERT INTO user_preferences (user_id, map_layers, updated_at) VALUES (:spike, CAST(:spike_layers AS jsonb), now()), "
        "(:other, CAST(:other_layers AS jsonb), now())",
        spike=SPIKE,
        other=OTHER,
        spike_layers=layers([("fr-geologie", True), ("fr-cadastre", True), ("fr-cadastre-etalab", False)]),
        other_layers=layers([("fr-cadastre", True)]),
    )
    run(
        before_0013,
        "INSERT INTO user_favorite_layers (user_id, layer_id, created_at) VALUES (:id, 'fr-cadastre', now()), (:id, 'fr-cadastre-etalab', now())",
        id=SPIKE,
    )

    remove_ign_cadastre(before_0013)

    assert values(before_0013, "SELECT layer_id FROM user_favorite_layers") == ["fr-cadastre-etalab"]
    kept = values(before_0013, "SELECT map_layers FROM user_preferences WHERE user_id = :id", id=SPIKE)[0]
    assert [layer["layer_id"] for layer in kept] == ["fr-geologie", "fr-cadastre-etalab"]
    assert values(before_0013, "SELECT map_layers FROM user_preferences WHERE user_id = :id", id=OTHER) == [[]]


def test_saved_investigations_show_the_etalab_cadastre_instead(before_0013):
    page_id = investigation_with(before_0013, ["fr-cadastre", "fr-cadastre-etalab", "fr-geologie"])

    remove_ign_cadastre(before_0013)

    assert stored_layer_ids(before_0013, page_id) == [["fr-cadastre-etalab", "fr-cadastre-etalab", "fr-geologie"]] * 2
