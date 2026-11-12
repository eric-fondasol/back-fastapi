import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.auth import Identity, current_identity
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
    paths = ["/admin/activity", "/admin/database/tables", "/admin/database/tables/user_roles", "/admin/database/tables/catalog_layers/columns/category_id/choices"]

    assert {call(client, "GET", path, identity=AGENT).status_code for path in paths} == {403}
    grant = {"values": {"user_id": user_id(client, AGENT), "role_code": "admin"}}
    assert call(client, "POST", "/admin/database/tables/user_roles/rows", grant, identity=AGENT).status_code == 403


def test_the_screens_replaced_by_the_table_views_are_gone(client):
    make_admin(client)

    paths = ["/admin/users", "/admin/business-units", "/admin/business-lines", "/admin/layer-categories", "/admin/catalog-layers", "/admin/referentials"]

    assert {call(client, "GET", path).status_code for path in paths} == {404}


def test_grant_admin_refuses_an_address_without_profile(client):
    assert grant_admin.main(["inconnu@fondasol.fr"]) == 1
    assert grant_admin.main([]) == 2


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
