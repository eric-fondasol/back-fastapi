import json
from urllib.parse import quote

import pytest
from sqlalchemy import text

from tests.domains.admin.test_routes import AGENT, call, client, execute, make_admin  # noqa: F401


def key(**values):
    return quote(json.dumps(values))


def scalar(engine, sql, **parameters):
    with engine.connect() as connection:
        return connection.execute(text(sql), parameters).scalar()


@pytest.fixture
def admin(client):  # noqa: F811
    make_admin(client)
    return client


def test_the_table_list_tells_which_tables_can_be_edited_and_emptied(admin):
    tables = {table["name"]: table for table in call(admin, "GET", "/admin/database/tables").json()}

    assert (tables["business_lines"]["editable"], tables["business_lines"]["deletable"]) == (True, True)
    assert (tables["users"]["editable"], tables["users"]["deletable"]) == (True, False)
    assert (tables["projects"]["editable"], tables["projects"]["deletable"]) == (True, False)
    assert (tables["parametrages"]["editable"], tables["parametrages"]["deletable"]) == (False, False)
    assert tables["user_roles"]["editable"] is False


def test_a_table_page_describes_which_columns_are_written_by_hand(admin):
    page = call(admin, "GET", "/admin/database/tables/catalog_layers").json()
    columns = {column["name"]: column for column in page["columns"]}

    assert (page["editable"], page["deletable"]) == (True, True)
    assert (columns["id"]["writable"], columns["id"]["hasDefault"]) == (True, True)
    assert (columns["code"]["writable"], columns["code"]["hasDefault"]) == (True, False)
    assert columns["updated_at"]["writable"] is False
    assert columns["updated_by"]["writable"] is False
    project_types = {column["name"]: column for column in call(admin, "GET", "/admin/database/tables/project_types").json()["columns"]}
    assert (project_types["id"]["writable"], project_types["id"]["hasDefault"]) == (False, True)


def test_a_row_is_created_read_updated_and_deleted(admin, refonte_database):
    created = call(admin, "POST", "/admin/database/tables/business_lines/rows", {"values": {"code": "GT", "label_fr": "Géotechnique", "position": "1"}})
    assert (created.status_code, created.json()) == (201, {"key": {"code": "GT"}})

    read = call(admin, "GET", f"/admin/database/tables/business_lines/row?key={key(code='GT')}").json()
    assert read == {"values": {"code": "GT", "label_fr": "Géotechnique", "label_en": None, "position": "1"}}

    updated = call(admin, "PATCH", "/admin/database/tables/business_lines/rows", {"key": {"code": "GT"}, "values": {"label_en": "Geotechnics", "position": None}})
    assert updated.json() == {"key": {"code": "GT"}}
    assert scalar(refonte_database, "SELECT label_en || coalesce(position::text, '∅') FROM business_lines WHERE code = 'GT'") == "Geotechnics∅"

    assert call(admin, "DELETE", f"/admin/database/tables/business_lines/rows?key={key(code='GT')}").status_code == 204
    assert scalar(refonte_database, "SELECT count(*) FROM business_lines") == 0


def test_identity_keys_are_generated_and_the_author_is_recorded(admin, refonte_database):
    created = call(admin, "POST", "/admin/database/tables/project_types/rows", {"values": {"libelle": "Maison individuelle"}}).json()
    assert created == {"key": {"id": "1"}}

    category = call(admin, "POST", "/admin/database/tables/layer_categories/rows", {"values": {"code": "fonds", "label_fr": "Fonds", "position": "1"}}).json()
    call(admin, "PATCH", "/admin/database/tables/layer_categories/rows", {"key": category["key"], "values": {"label_fr": "Fonds de plan"}})

    assert scalar(refonte_database, "SELECT updated_by FROM layer_categories WHERE code = 'fonds'") == "admin@fondasol.fr"


def test_a_composite_key_designates_one_row(admin, refonte_database):
    for level in ("1", "2"):
        call(admin, "POST", "/admin/database/tables/geolocation_reliabilities/rows", {"values": {"scope": "survey", "level": level, "reliability": "reliable", "libelle": f"Niveau {level}"}})

    call(admin, "PATCH", "/admin/database/tables/geolocation_reliabilities/rows", {"key": {"scope": "survey", "level": "2"}, "values": {"libelle": "Deux"}})

    assert scalar(refonte_database, "SELECT string_agg(libelle, ',' ORDER BY level) FROM geolocation_reliabilities") == "Niveau 1,Deux"


def test_geometries_are_written_in_wkt_with_the_srid_of_the_column(admin, refonte_database):
    response = call(
        admin,
        "POST",
        "/admin/database/tables/fuseau_works/rows",
        {"values": {"name": "Chantier", "type_reference": "1", "center": "POINT(1.44 43.6)"}},
    )

    assert response.status_code == 201
    assert scalar(refonte_database, "SELECT ST_SRID(center) || ' ' || ST_AsText(center) FROM fuseau_works") == "4326 POINT(1.44 43.6)"
    assert call(admin, "GET", f"/admin/database/tables/fuseau_works/row?key={quote(json.dumps(response.json()['key']))}").json()["values"]["center"] == "POINT(1.44 43.6)"


@pytest.mark.parametrize(
    "values",
    [
        {"libelle": "x", "id": "abc"},
        {"name": "Chantier", "type_reference": "un", "center": "POINT(1 2)"},
        {"name": "Chantier", "type_reference": "1", "center": "POINT(1"},
    ],
)
def test_a_value_postgresql_cannot_read_is_refused_with_its_reason(admin, values):
    table = "project_types" if "libelle" in values else "fuseau_works"

    response = call(admin, "POST", f"/admin/database/tables/{table}/rows", {"values": values})

    assert response.status_code in (400, 422)
    assert response.json()["errors"]


def test_invalid_json_is_refused(admin):
    response = call(
        admin,
        "POST",
        "/admin/database/tables/saved_page_versions/rows",
        {"values": {"id": "1d0e7a52-0f6c-4c58-9d7e-2b5b6b0b9c11", "saved_page_id": "1", "version": "1", "data": "{pas du json"}},
    )

    assert response.status_code == 422
    assert "Valeur refusée" in response.json()["errors"]


def test_a_duplicate_key_is_a_conflict(admin):
    call(admin, "POST", "/admin/database/tables/referentiels/rows", {"values": {"code": "NGF", "label_fr": "NGF"}})

    response = call(admin, "POST", "/admin/database/tables/referentiels/rows", {"values": {"code": "NGF", "label_fr": "Autre"}})

    assert response.status_code == 409


def test_the_deletion_impact_lists_cascades_and_blockers(admin, refonte_database):
    execute(refonte_database, "INSERT INTO business_lines (code, label_fr) VALUES ('GT', 'GT')")
    execute(refonte_database, "INSERT INTO business_units (code, libelle, business_line) VALUES ('31GT', 'Toulouse', 'GT')")
    execute(refonte_database, "INSERT INTO saved_pages (uuid, reference) VALUES (gen_random_uuid(), 'A')")
    page_id = scalar(refonte_database, "SELECT id FROM saved_pages")
    execute(
        refonte_database,
        "INSERT INTO saved_page_versions (id, saved_page_id, version, data) VALUES (gen_random_uuid(), :page, 1, '{}'), (gen_random_uuid(), :page, 2, '{}')",
        page=page_id,
    )

    blocked = call(admin, "GET", f"/admin/database/tables/business_lines/deletion?key={key(code='GT')}").json()
    cascading = call(admin, "GET", f"/admin/database/tables/saved_pages/deletion?key={key(id=str(page_id))}").json()

    assert blocked == {"cascades": [], "blockers": [{"table": "business_units", "rows": 1}], "detached": []}
    assert cascading["cascades"] == [{"table": "saved_page_versions", "rows": 2}]
    assert call(admin, "DELETE", f"/admin/database/tables/business_lines/rows?key={key(code='GT')}").status_code == 409
    assert call(admin, "DELETE", f"/admin/database/tables/saved_pages/rows?key={key(id=str(page_id))}").status_code == 204
    assert scalar(refonte_database, "SELECT count(*) FROM saved_page_versions") == 0


def test_the_rules_of_the_editor_are_enforced_by_the_server(admin):
    me = call(admin, "GET", "/me").json()["id"]

    assert call(admin, "DELETE", f"/admin/database/tables/users/rows?key={key(id=me)}").status_code == 422
    assert call(admin, "POST", "/admin/database/tables/parametrages/rows", {"values": {"email": "a@b.fr"}}).status_code == 422
    assert call(admin, "POST", "/admin/database/tables/user_roles/rows", {"values": {}}).status_code == 422
    assert call(admin, "POST", "/admin/database/tables/inconnue/rows", {"values": {}}).status_code == 404
    assert call(admin, "PATCH", "/admin/database/tables/users/rows", {"key": {"id": me}, "values": {"id": me}}).status_code == 400
    assert call(admin, "PATCH", "/admin/database/tables/users/rows", {"key": {"id": me}, "values": {"inconnue": "x"}}).status_code == 400
    assert call(admin, "PATCH", "/admin/database/tables/users/rows", {"key": {"id": me}, "values": {"email": None}}).status_code == 400
    assert call(admin, "GET", "/admin/database/tables/users/row?key=pas-du-json").status_code == 400
    assert call(admin, "GET", f"/admin/database/tables/users/row?key={key(email='x')}").status_code == 400
    assert call(admin, "GET", f"/admin/database/tables/business_lines/row?key={key(code='x')}", identity=AGENT).status_code == 403


def test_key_values_are_never_read_as_sql(admin, refonte_database):
    execute(refonte_database, "INSERT INTO business_lines (code, label_fr) VALUES ('GT', 'GT')")

    injected = key(code="x' OR '1'='1")

    response = call(admin, "DELETE", f"/admin/database/tables/business_lines/rows?key={injected}")

    assert response.status_code == 404
    assert scalar(refonte_database, "SELECT count(*) FROM business_lines") == 1


def test_a_check_constraint_refusal_explains_itself(admin):
    response = call(
        admin,
        "POST",
        "/admin/database/tables/geolocation_reliabilities/rows",
        {"values": {"scope": "survey", "level": "1", "reliability": "ok", "libelle": "Niveau 1"}},
    )

    assert response.status_code == 422
    assert "geolocation_reliabilities" in response.json()["errors"]
