import json
from urllib.parse import quote

import pytest
from sqlalchemy import text

from app.core.profile import Profile
from app.core.errors import Conflict
from app.domains.admin import editing
from tests.domains.admin.test_routes import ADMIN, AGENT, OTHER_ADMIN, call, client, execute, make_admin, user_id  # noqa: F401


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
    assert (tables["user_roles"]["editable"], tables["user_roles"]["deletable"]) == (True, True)


def test_a_table_page_describes_which_columns_are_written_by_hand(admin):
    page = call(admin, "GET", "/admin/database/tables/catalog_layers").json()
    columns = {column["name"]: column for column in page["columns"]}

    assert (page["editable"], page["deletable"]) == (True, True)
    assert (columns["id"]["writable"], columns["id"]["hasDefault"]) == (False, True)
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


def test_a_column_that_points_to_another_table_names_it_and_proposes_its_rows_by_label(admin, refonte_database):
    execute(refonte_database, "INSERT INTO layer_categories (code, label_fr, position) VALUES ('geologie', 'Géologie', 1), ('eaux', 'Eaux', 2)")

    columns = {column["name"]: column for column in call(admin, "GET", "/admin/database/tables/layer_categories").json()["columns"]}
    choices = call(admin, "GET", "/admin/database/tables/layer_categories/columns/parent_id/choices").json()

    assert (columns["parent_id"]["reference"], columns["code"]["reference"]) == ("layer_categories", None)
    assert choices["table"] == "layer_categories"
    assert choices["truncated"] is False
    assert [choice["label"] for choice in choices["choices"]] == ["Eaux", "Géologie"]
    assert {choice["value"] for choice in choices["choices"]} == set(
        str(value) for value in [scalar(refonte_database, "SELECT id FROM layer_categories WHERE code = 'eaux'"), scalar(refonte_database, "SELECT id FROM layer_categories WHERE code = 'geologie'")]
    )


def test_the_rows_of_a_referenced_table_are_named_by_their_most_readable_column(admin):
    roles = call(admin, "GET", "/admin/database/tables/user_roles/columns/role_code/choices").json()["choices"]
    users = call(admin, "GET", "/admin/database/tables/user_roles/columns/user_id/choices").json()["choices"]

    assert "admin" in {choice["value"] for choice in roles}
    assert [choice["label"] for choice in users] == ["Admin Test"]
    assert editing.label_column(["id", "code", "label_fr"], "id") == "label_fr"
    assert editing.label_column(["id", "uuid"], "id") == "id"


def test_choices_are_refused_for_a_column_without_link_or_an_unknown_table(admin):
    assert call(admin, "GET", "/admin/database/tables/layer_categories/columns/code/choices").status_code == 404
    assert call(admin, "GET", "/admin/database/tables/inconnue/columns/id/choices").status_code == 404


def test_beyond_the_limit_the_choices_are_truncated(admin, monkeypatch):
    monkeypatch.setattr("app.domains.admin.services.MAX_CHOICES", 0)

    choices = call(admin, "GET", "/admin/database/tables/user_roles/columns/user_id/choices").json()

    assert (choices["choices"], choices["truncated"]) == ([], True)


def test_a_role_is_granted_then_withdrawn_through_the_user_roles_table(admin, refonte_database):
    call(admin, "GET", "/me", identity=AGENT)
    agent = user_id(admin, AGENT)

    granted = call(admin, "POST", "/admin/database/tables/user_roles/rows", {"values": {"user_id": agent, "role_code": "admin"}})
    assert granted.status_code == 201
    assert scalar(refonte_database, "SELECT granted_at IS NOT NULL FROM user_roles WHERE user_id = :id AND role_code = 'admin'", id=agent)

    withdrawn = call(admin, "DELETE", f"/admin/database/tables/user_roles/rows?key={key(user_id=agent, role_code='admin')}")
    assert withdrawn.status_code == 204
    assert call(admin, "GET", "/admin/database/tables", identity=AGENT).status_code == 403


def test_an_admin_cannot_withdraw_their_own_admin_role(admin):
    make_admin(admin, OTHER_ADMIN)

    response = call(admin, "DELETE", f"/admin/database/tables/user_roles/rows?key={key(user_id=user_id(admin, ADMIN), role_code='admin')}")

    assert response.status_code == 409
    assert "propre rôle" in response.json()["errors"]


def test_the_last_admin_cannot_be_withdrawn_by_a_caller_who_lost_the_role_meanwhile(admin):
    call(admin, "GET", "/me", identity=AGENT)
    former_admin = Profile(user_id(admin, AGENT), AGENT.azure_oid, AGENT.username, AGENT.name, roles=("user",))

    with pytest.raises(Conflict, match="au moins un administrateur"):
        editing.delete_row(former_admin, "user_roles", json.dumps({"user_id": user_id(admin, ADMIN), "role_code": "admin"}))


def test_withdrawing_the_user_role_is_not_guarded(admin):
    call(admin, "GET", "/me", identity=AGENT)

    response = call(admin, "DELETE", f"/admin/database/tables/user_roles/rows?key={key(user_id=user_id(admin, AGENT), role_code='user')}")

    assert response.status_code == 204


def test_a_generated_primary_key_is_never_written_by_hand(admin, refonte_database):
    columns = {column["name"]: column for column in call(admin, "GET", "/admin/database/tables/layer_categories").json()["columns"]}
    assert (columns["id"]["writable"], columns["code"]["writable"]) == (False, True)
    roles = {column["name"]: column for column in call(admin, "GET", "/admin/database/tables/user_roles").json()["columns"]}
    assert (roles["user_id"]["writable"], roles["role_code"]["writable"]) == (True, True)

    forced = call(admin, "POST", "/admin/database/tables/layer_categories/rows", {"values": {"id": "00000000-0000-4000-8000-000000000000", "code": "x", "label_fr": "X", "position": "1"}})
    created = call(admin, "POST", "/admin/database/tables/layer_categories/rows", {"values": {"code": "eaux", "label_fr": "Eaux", "position": "1"}})

    assert forced.status_code == 400
    assert created.status_code == 201
    assert created.json()["key"]["id"] == str(scalar(refonte_database, "SELECT id FROM layer_categories WHERE code = 'eaux'"))
