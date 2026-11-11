import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.auth import Identity, current_identity
from app.core.errors import Conflict
from app.core.profile import Profile
from app.domains.admin import grant_admin, services
from app.main import app

ADMIN = Identity("admin@fondasol.fr", "6f1c2a3e-0b1d-4c55-9a77-1f2e3d4c5b6a", "Admin Test")
AGENT = Identity("agent@fondasol.fr", "7a2d3b4f-1c2e-4d66-8b88-2a3f4e5d6c7b", "Agent Test")
OTHER_ADMIN = Identity("autre.admin@fondasol.fr", "8b3e4c5a-2d3f-4e77-9c99-3b4a5f6e7d8c", "Autre Admin")


@pytest.fixture
def client(refonte_database):
    caller = {"identity": ADMIN}
    app.dependency_overrides[current_identity] = lambda: caller["identity"]
    with TestClient(app) as test_client:
        test_client.caller = caller
        yield test_client
    app.dependency_overrides.clear()


def call(client, method, path, body=None, identity=ADMIN):
    client.caller["identity"] = identity
    return client.request(method, path, json=body)


def execute(engine, sql, **parameters):
    with engine.begin() as connection:
        connection.execute(text(sql), parameters)


def make_admin(client, identity=ADMIN):
    call(client, "GET", "/me", identity=identity)
    assert grant_admin.main([identity.username]) == 0


def user_id(client, identity):
    return call(client, "GET", "/me", identity=identity).json()["id"]


@pytest.fixture
def catalog(refonte_database):
    execute(refonte_database, "INSERT INTO layer_categories (code, label_fr, label_en, position) VALUES ('fonds', 'Fonds', 'Base maps', 1), ('geologie', 'Géologie', NULL, 2), ('vide', 'Vide', NULL, 3)")
    execute(
        refonte_database,
        """
        INSERT INTO catalog_layers (code, category_id, country, label_fr, kind, url, attribution, position, enabled)
        SELECT 'fr-plan', id, 'fr', 'Plan IGN', 'wmts', 'https://data.geopf.fr/wmts', 'IGN', 1, true FROM layer_categories WHERE code = 'fonds'
        """,
    )


def test_a_new_profile_has_the_user_role_only(client):
    assert call(client, "GET", "/me", identity=AGENT).json()["roles"] == ["user"]


def test_every_admin_route_refuses_an_agent_without_the_admin_role(client):
    paths = ["/admin/users", "/admin/activity", "/admin/business-units", "/admin/business-lines", "/admin/layer-categories", "/admin/catalog-layers", "/admin/referentials"]

    assert {call(client, "GET", path, identity=AGENT).status_code for path in paths} == {403}
    assert call(client, "PUT", f"/admin/users/{user_id(client, AGENT)}/role", {"role": "admin"}, identity=AGENT).status_code == 403


def test_grant_admin_refuses_an_address_without_profile(client):
    assert grant_admin.main(["inconnu@fondasol.fr"]) == 1
    assert grant_admin.main([]) == 2


def test_an_admin_sees_the_users_with_their_roles(client):
    make_admin(client)
    call(client, "GET", "/me", identity=AGENT)

    users = call(client, "GET", "/admin/users").json()

    assert [(user["email"], user["roles"]) for user in users] == [("admin@fondasol.fr", ["admin", "user"]), ("agent@fondasol.fr", ["user"])]


def test_an_admin_grants_then_withdraws_the_admin_role(client):
    make_admin(client)
    agent = user_id(client, AGENT)

    granted = call(client, "PUT", f"/admin/users/{agent}/role", {"role": "admin"})
    withdrawn = call(client, "PUT", f"/admin/users/{agent}/role", {"role": "user"})

    assert (granted.status_code, granted.json()["roles"]) == (200, ["admin", "user"])
    assert (withdrawn.status_code, withdrawn.json()["roles"]) == (200, ["user"])
    assert call(client, "GET", "/admin/users", identity=AGENT).status_code == 403


def test_an_admin_cannot_withdraw_their_own_admin_role(client):
    make_admin(client)
    make_admin(client, OTHER_ADMIN)

    response = call(client, "PUT", f"/admin/users/{user_id(client, ADMIN)}/role", {"role": "user"})

    assert response.status_code == 409
    assert "propre rôle" in response.json()["errors"]


def test_the_last_admin_cannot_be_withdrawn_by_a_caller_who_lost_the_role_meanwhile(client):
    make_admin(client)
    former_admin = Profile(user_id(client, AGENT), AGENT.azure_oid, AGENT.username, AGENT.name, roles=("user",))

    with pytest.raises(Conflict, match="au moins un administrateur"):
        services.change_role(former_admin, user_id(client, ADMIN), {"role": "user"})


def test_a_role_change_checks_the_role_and_the_user(client):
    make_admin(client)

    assert call(client, "PUT", f"/admin/users/{user_id(client, AGENT)}/role", {"role": "chef"}).status_code == 400
    assert call(client, "PUT", "/admin/users/00000000-0000-4000-8000-000000000000/role", {"role": "admin"}).status_code == 404
    assert call(client, "PUT", "/admin/users/pas-un-uuid/role", {"role": "admin"}).status_code == 404


def test_activity_counts_the_active_agents_and_the_server_errors(client, refonte_database):
    make_admin(client)
    execute(
        refonte_database,
        """
        INSERT INTO usage_logs (request_id, username, method, path, status_code, duration_ms) VALUES
            (gen_random_uuid(), 'admin@fondasol.fr', 'GET', '/me', 200, 5),
            (gen_random_uuid(), 'AGENT@fondasol.fr', 'GET', '/me', 500, 5),
            (gen_random_uuid(), 'agent@fondasol.fr', 'GET', '/me', 200, 5),
            (gen_random_uuid(), NULL, 'GET', '/api/health', 200, 1)
        """,
    )

    activity = call(client, "GET", "/admin/activity").json()

    assert (activity["activeUsers"], activity["requests"], activity["serverErrors"]) == (2, 4, 1)
    assert len(activity["weeklyActiveUsers"]) == 8
    assert activity["weeklyActiveUsers"][-1]["activeUsers"] == 2
    assert len(activity["dailyRequests"]) == 30
    assert activity["dailyRequests"][-1] == {"day": activity["dailyRequests"][-1]["day"], "requests": 4, "serverErrors": 1}
    assert activity["responseTimeMs"]["p50"] == 5.0
    assert [table["table"] for table in activity["dataVolumes"]] == ["projects", "sites", "surveys", "lithologies", "pressures", "saved_pages"]


def test_activity_ranks_the_most_used_actions(client, refonte_database):
    make_admin(client)
    execute(
        refonte_database,
        """
        INSERT INTO usage_logs (request_id, username, action, method, path, status_code, duration_ms) VALUES
            (gen_random_uuid(), 'a@fondasol.fr', 'project', 'GET', '/projects/1', 200, 5),
            (gen_random_uuid(), 'a@fondasol.fr', 'project', 'GET', '/projects/2', 200, 5),
            (gen_random_uuid(), 'a@fondasol.fr', 'search', 'GET', '/projects', 200, 5),
            (gen_random_uuid(), 'a@fondasol.fr', NULL, 'GET', '/api/health', 200, 5)
        """,
    )

    assert call(client, "GET", "/admin/activity").json()["topActions"] == [{"action": "project", "requests": 2}, {"action": "search", "requests": 1}]


def test_layer_categories_are_listed_created_renamed_reordered_and_deleted(client, catalog):
    make_admin(client)

    listed = call(client, "GET", "/admin/layer-categories").json()
    created = call(client, "POST", "/admin/layer-categories", {"code": "sismicite", "labelFr": "Sismicité", "labelEn": "Seismicity"})
    renamed = call(client, "PATCH", "/admin/layer-categories/geologie", {"labelFr": "Géologie", "labelEn": "Geology"})
    reordered = call(client, "PUT", "/admin/layer-categories/order", {"codes": ["sismicite", "geologie", "fonds", "vide"]})
    deleted = call(client, "DELETE", "/admin/layer-categories/vide")

    assert [(row["code"], row["layers"]) for row in listed] == [("fonds", 1), ("geologie", 0), ("vide", 0)]
    assert (created.status_code, created.json()["position"]) == (201, 4)
    assert renamed.json()["label"] == {"fr": "Géologie", "en": "Geology"}
    assert [row["code"] for row in reordered.json()] == ["sismicite", "geologie", "fonds", "vide"]
    assert deleted.status_code == 204
    assert [row["code"] for row in call(client, "GET", "/admin/layer-categories").json()] == ["sismicite", "geologie", "fonds"]


def test_layer_category_rules(client, catalog):
    make_admin(client)

    assert call(client, "POST", "/admin/layer-categories", {"code": "Fonds", "labelFr": "X"}).status_code == 400
    assert call(client, "POST", "/admin/layer-categories", {"code": "fonds", "labelFr": "X"}).status_code == 409
    assert call(client, "POST", "/admin/layer-categories", {"code": "neuve", "labelFr": " "}).status_code == 400
    assert call(client, "PUT", "/admin/layer-categories/order", {"codes": ["fonds", "geologie"]}).status_code == 400
    assert call(client, "DELETE", "/admin/layer-categories/fonds").status_code == 409
    assert call(client, "DELETE", "/admin/layer-categories/absente").status_code == 404


def test_a_catalog_layer_changes_category_and_activation_only(client, catalog, refonte_database):
    make_admin(client)

    changed = call(client, "PATCH", "/admin/catalog-layers/fr-plan", {"category": "geologie", "enabled": False})

    assert (changed.json()["category"], changed.json()["enabled"]) == ("geologie", False)
    assert call(client, "PATCH", "/admin/catalog-layers/fr-plan", {"url": "https://ailleurs"}).status_code == 400
    assert call(client, "PATCH", "/admin/catalog-layers/fr-plan", {"category": "absente"}).status_code == 400
    assert call(client, "PATCH", "/admin/catalog-layers/absente", {"enabled": True}).status_code == 404
    with refonte_database.connect() as connection:
        assert connection.execute(text("SELECT updated_by FROM catalog_layers")).scalar_one() == "admin@fondasol.fr"
    assert call(client, "GET", "/layer-catalog").json()["layers"] == []


def test_business_line_labels_are_updated(client, refonte_database):
    make_admin(client)
    execute(refonte_database, "INSERT INTO business_lines (code, label_fr, position) VALUES ('GT', 'GT', 1)")

    updated = call(client, "PATCH", "/admin/business-lines/GT", {"labelFr": "Géotechnique", "labelEn": "Geotechnics"})

    assert updated.json() == {"code": "GT", "label": {"fr": "Géotechnique", "en": "Geotechnics"}, "position": 1}
    assert call(client, "PATCH", "/admin/business-lines/ZZ", {"labelFr": "X"}).status_code == 404


def test_business_units_count_their_agents(client, refonte_database):
    execute(refonte_database, "INSERT INTO business_lines (code, label_fr, position) VALUES ('GT', 'GT', 1)")
    execute(refonte_database, "INSERT INTO business_units (code, libelle, business_line, full_access) VALUES ('31GT', 'Toulouse', 'GT', false), ('GFIT', 'Informatique', NULL, true)")
    make_admin(client)
    execute(refonte_database, "UPDATE users SET business_unit_code = '31GT'")

    units = call(client, "GET", "/admin/business-units").json()

    assert units == [
        {"code": "31GT", "label": "Toulouse", "businessLine": "GT", "fullAccess": False, "users": 1},
        {"code": "GFIT", "label": "Informatique", "businessLine": None, "fullAccess": True, "users": 0},
    ]


def test_referentials_are_read(client, refonte_database):
    make_admin(client)
    execute(refonte_database, "INSERT INTO no_docs_ged_reasons (id, libelle) VALUES (1, 'Documents introuvables')")

    referentials = call(client, "GET", "/admin/referentials").json()

    assert referentials["noDocsGedReasons"] == [{"code": "1", "label": "Documents introuvables"}]
    assert set(referentials) == {"altimetricReferences", "noDocsGedReasons", "geolocationReliabilities"}


def test_the_database_explorer_lists_the_public_tables(client, catalog):
    make_admin(client)

    tables = {table["name"]: table for table in call(client, "GET", "/admin/database/tables").json()}

    assert {"users", "user_roles", "layer_categories", "catalog_layers"} <= set(tables)
    assert tables["layer_categories"]["columns"] == 9
    assert "pg_class" not in tables


def test_a_table_page_gives_the_columns_and_text_rows_ordered_by_primary_key(client, catalog):
    make_admin(client)

    page = call(client, "GET", "/admin/database/tables/layer_categories?limit=25&offset=1").json()

    assert [column["name"] for column in page["columns"]][:3] == ["id", "code", "label_fr"]
    assert next(column for column in page["columns"] if column["name"] == "id")["primaryKey"] is True
    assert (page["offset"], page["limit"], page["hasMore"], len(page["rows"])) == (1, 25, False, 2)
    assert all(value is None or isinstance(value, str) for row in page["rows"] for value in row)


def test_a_table_page_shows_geometries_as_text_and_cuts_long_values(client, refonte_database):
    make_admin(client)
    execute(refonte_database, "CREATE TABLE explorer_probe (id integer PRIMARY KEY, geom geometry(Point, 4326), note text)")
    try:
        execute(refonte_database, "INSERT INTO explorer_probe VALUES (1, ST_SetSRID(ST_MakePoint(1.5, 43.6), 4326), :note)", note="x" * 400)

        page = call(client, "GET", "/admin/database/tables/explorer_probe").json()

        assert page["rows"] == [["1", "POINT(1.5 43.6)", "x" * 300 + "…"]]
        assert [column["type"] for column in page["columns"]] == ["integer", "geometry(Point,4326)", "text"]
    finally:
        execute(refonte_database, "DROP TABLE explorer_probe")


def test_a_table_page_pages_with_has_more(client, refonte_database):
    make_admin(client)
    for index in range(3):
        execute(refonte_database, "INSERT INTO business_lines (code, label_fr, position) VALUES (:code, :code, :position)", code=f"L{index}", position=index)

    first = call(client, "GET", "/admin/database/tables/business_lines?limit=25").json()

    assert (first["hasMore"], len(first["rows"])) == (False, 3)
    assert call(client, "GET", "/admin/database/tables/business_lines?offset=2").json()["rows"][0][0] == "L2"


def test_the_database_explorer_refuses_unknown_tables_and_bad_pages(client):
    make_admin(client)

    assert call(client, "GET", "/admin/database/tables/pg_authid").status_code == 404
    assert call(client, "GET", '/admin/database/tables/users"; DROP TABLE users; --').status_code == 404
    assert call(client, "GET", "/admin/database/tables/users?limit=1000").status_code == 400
    assert call(client, "GET", "/admin/database/tables/users?offset=-1").status_code == 400
    assert call(client, "GET", "/admin/database/tables", identity=AGENT).status_code == 403


def test_a_too_slow_table_read_gives_a_readable_refusal(client, monkeypatch):
    make_admin(client)
    monkeypatch.setattr(services, "TABLE_READ_TIMEOUT_MS", 1)
    monkeypatch.setattr(services.queries, "table_rows", _slow_rows)

    response = call(client, "GET", "/admin/database/tables/users")

    assert response.status_code == 422
    assert "trop longue" in response.json()["errors"]


def _slow_rows(connection, *_):
    connection.execute(text("SET LOCAL statement_timeout = 1"))
    connection.execute(text("SELECT pg_sleep(1)"))
