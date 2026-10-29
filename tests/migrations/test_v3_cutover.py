import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

WAREHOUSE_ID = "5a02c2aa-2aa9-4b5b-9c93-20eb764d3ba7"
USER_ID = "00000000-0000-0000-0000-000000000001"


def run(database, *statements):
    with database.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def rows(database, query):
    with database.connect() as connection:
        return connection.execute(text(query)).all()


@pytest.fixture
def former_schema(schema_at):
    database = schema_at("0014")
    run(
        database,
        "INSERT INTO business_units (code, libelle, business_line) VALUES ('77GT', 'Marne-la-Vallée', 'GT')",
        f"INSERT INTO users (id, email, created_at) VALUES ('{USER_ID}', 'agent@fondasol.fr', now())",
        """
        INSERT INTO projects (id, name, code_metier, is_doc_ged, altitude, geometry, longitude_saisie, latitude_saisie,
                              systeme_geo, city_agency, is_doc_ged_updated_by, is_doc_ged_updated_at)
        VALUES ('77GT.19.0220', 'Gymnase', 'GT', true, 112.5, ST_SetSRID(ST_MakePoint(2.6, 48.85), 4326), 2.61, 48.86,
                'WGS 1984', '77GT', 'agent@fondasol.fr', '2026-10-20 10:00'),
               ('ZZ.99.0001', 'Inconnue de l''entrepôt', 'N/A', false, NULL, NULL, 1.44, 43.6, NULL, NULL, NULL, NULL)
        """,
        """
        INSERT INTO sites (id, project_id, fiability, updated_at, geometry) VALUES
            ('77GT.19.0220', '77GT.19.0220', 1, now(), ST_SetSRID(ST_MakePoint(2.6, 48.85), 4326)),
            ('ZZ.99.0001', 'ZZ.99.0001', NULL, NULL, NULL)
        """,
        """
        INSERT INTO surveys (id, site_id, city, geometry, longitude_saisie, latitude_saisie, systeme_geo) VALUES
            ('77GT.19.0220_SP_2', '77GT.19.0220', 'Meaux', ST_SetSRID(ST_MakePoint(2.601, 48.851), 4326), NULL, NULL, NULL),
            ('77GT.19.0220_NvS1', '77GT.19.0220', NULL, NULL, 2.602, 48.852, 'WGS 1984'),
            ('ZZ.99.0001_P1', 'ZZ.99.0001', NULL, NULL, 600000, 6200000, 'Lambert 93')
        """,
        "INSERT INTO lithologies (id, survey_id, type, comment) VALUES ('L1', '77GT.19.0220_SP_2', 'REM', 'Remblai')",
        "INSERT INTO pressures (id, survey_id, depth, pressiometric_test, creep_pressure, limit_pressure, h_gama) VALUES ('P1', '77GT.19.0220_SP_2', 2, 12.5, 0.8, 1.4, 0.1)",
        f"INSERT INTO user_favorite_projects (user_id, project_id, created_at) VALUES ('{USER_ID}', '77GT.19.0220', now())",
        """
        INSERT INTO saved_pages (id, uuid, data, data_api, email, project_ref, created_at, updated_at) VALUES
            (1, gen_random_uuid(), '{"coordinates":{"lng": 2.6,"lat": 48.85}}', '{}', 'AGENT@fondasol.fr', 'PR.77GT.19.0220', now(), now()),
            (2, gen_random_uuid(), '{"coordinates":{"lng": 1.4,"lat": 43.6}}', NULL, 'autre@fondasol.fr', 'SQ.31GT.26.10.025', now(), now()),
            (3, gen_random_uuid(), '{"coordinates":{"lng": 3,"lat": 45}}', NULL, NULL, '', now(), now())
        """,
        """
        INSERT INTO saved_page_versions (id, saved_page_id, version, data, created_at) VALUES
            (gen_random_uuid(), 1, 1, '{"coordinates":{"lng": 2.6,"lat": 48.85}}', now()),
            (gen_random_uuid(), 2, 1, '{"coordinates":{"lng": 1.4,"lat": 43.6}}', now())
        """,
        "INSERT INTO departments (id, libelle, code_service) VALUES ('77', 'Seine-et-Marne', '77GT')",
        f"""
        INSERT INTO user_layers (id, user_id, name, kind, url, west, south, east, north, created_at, updated_at)
        VALUES (gen_random_uuid(), '{USER_ID}', 'WMS', 'wms', 'https://example.test/wms', 1, 2, 3, 4, now(), now())
        """,
    )
    return database


def stage_warehouse(database):
    run(
        database,
        f"INSERT INTO v3_warehouse_projects VALUES ('77GT.19.0220', '{WAREHOUSE_ID}', '77GT', 1)",
        """
        INSERT INTO v3_warehouse_surveys VALUES
            ('77GT.19.0220', '77GT.19.0220_SP_2', 2, true, false, true, true, 'Calcaire de Champigny')
        """,
    )


def test_refuses_to_switch_project_ids_before_the_warehouse_data_is_staged(former_schema):
    with pytest.raises(Exception, match="v3_warehouse_projects est vide"):
        command.upgrade(ALEMBIC, "0015")


def test_projects_take_the_warehouse_id_and_keep_their_number(former_schema):
    stage_warehouse(former_schema)

    command.upgrade(ALEMBIC, "head")

    projects = dict(rows(former_schema, "SELECT project_number, id FROM projects"))
    assert projects["77GT.19.0220"] == WAREHOUSE_ID
    assert len(projects["ZZ.99.0001"]) == 36
    assert rows(former_schema, "SELECT project_id FROM sites WHERE id = '77GT.19.0220'") == [(WAREHOUSE_ID,)]
    assert rows(former_schema, "SELECT project_id FROM user_favorite_projects") == [(WAREHOUSE_ID,)]
    assert rows(
        former_schema,
        f"SELECT project_description, business_unit_code, fiab_geo_project FROM projects WHERE id = '{WAREHOUSE_ID}'",
    ) == [("Gymnase", "77GT", 1)]
    assert rows(former_schema, "SELECT project_id, business_line_code FROM project_business_lines") == [(WAREHOUSE_ID, "GT")]
    assert rows(former_schema, "SELECT project_id, is_doc_ged_new_value, user_email FROM docs_ged_changes") == [
        (WAREHOUSE_ID, True, "agent@fondasol.fr")
    ]
    assert rows(former_schema, "SELECT count(*) FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'code_metier'") == [(0,)]


def test_sites_carry_the_position_and_surveys_the_warehouse_data(former_schema):
    stage_warehouse(former_schema)

    command.upgrade(ALEMBIC, "head")

    assert rows(former_schema, "SELECT id, longitude, latitude, altitude, fiab_geo_sites FROM sites ORDER BY id") == [
        ("77GT.19.0220", 2.6, 48.85, 112.5, 1),
        ("ZZ.99.0001", 1.44, 43.6, None, None),
    ]
    assert rows(
        former_schema,
        """
        SELECT id, name, fiab_geo_surveys, has_pressuremeter, has_penetrometer, has_lithology, has_water_levels,
               geological_notation, longitude, latitude, has_pz_equipment
        FROM surveys ORDER BY id
        """,
    ) == [
        ("77GT.19.0220_NvS1", "NvS1", None, False, False, False, None, None, 2.602, 48.852, False),
        ("77GT.19.0220_SP_2", "SP_2", 2, True, False, True, True, "Calcaire de Champigny", 2.601, 48.851, False),
        ("ZZ.99.0001_P1", "P1", None, False, False, False, None, None, None, None, False),
    ]
    assert rows(former_schema, "SELECT description_fr FROM lithologies") == [("Remblai",)]
    assert rows(former_schema, "SELECT em, pf, pl, p0 FROM pressures") == [(12.5, 0.8, 1.4, 0.1)]


def test_investigations_keep_their_content_in_versions_and_get_their_reference_type_and_author(former_schema):
    stage_warehouse(former_schema)

    command.upgrade(ALEMBIC, "head")

    assert rows(former_schema, "SELECT id, reference, type_reference, user_id::text FROM saved_pages ORDER BY id") == [
        (1, "PR.77GT.19.0220", 1, USER_ID),
        (2, "SQ.31GT.26.10.025", 0, None),
        (3, "", 2, None),
    ]
    assert rows(former_schema, "SELECT saved_page_id, version, data -> 'coordinates' ->> 'lat' FROM saved_page_versions ORDER BY saved_page_id") == [
        (1, 1, "48.85"),
        (2, 1, "43.6"),
        (3, 1, "45"),
    ]
    assert rows(former_schema, "SELECT data_type FROM information_schema.columns WHERE table_name = 'saved_page_versions' AND column_name = 'data'") == [("jsonb",)]


def test_former_tables_go_and_the_new_ones_are_created(former_schema):
    stage_warehouse(former_schema)

    command.upgrade(ALEMBIC, "head")

    tables = {name for (name,) in rows(former_schema, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    assert tables.isdisjoint(
        {"services", "email_services", "service_departments", "access_limited_zones", "statistique_visites", "v3_warehouse_projects", "v3_project_ids"}
    )
    assert {
        "penetrometer_tests",
        "penetrometer_readings",
        "water_levels_manual",
        "water_levels_automatic",
        "geolocation_reliabilities",
        "fuseau_works",
        "fuseau_work_versions",
        "saved_page_version_files",
        "no_docs_ged_reasons",
    } <= tables
    assert rows(former_schema, "SELECT id, business_unit_codes FROM departments") == [("77", "77GT")]
    assert rows(former_schema, "SELECT count(*) FROM information_schema.columns WHERE table_name = 'user_layers' AND column_name = 'west'") == [(0,)]
