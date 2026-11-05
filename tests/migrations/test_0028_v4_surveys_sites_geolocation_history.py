import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

ALEMBIC = AlembicConfig("alembic.ini")

PROJECT = "5a02c2aa-2aa9-4b5b-9c93-20eb764d3ba7"
SITE = "77GT.19.0220"
SURVEY = "77GT.19.0220_SP_2"


def run(database, *statements):
    with database.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def rows(database, query):
    with database.connect() as connection:
        return connection.execute(text(query)).all()


def columns(database, table):
    return [
        row[0]
        for row in rows(
            database,
            f"SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = '{table}' ORDER BY ordinal_position",
        )
    ]


def table_exists(database, table):
    return rows(database, f"SELECT to_regclass('public.{table}') IS NOT NULL")[0][0]


@pytest.fixture
def before_0028(schema_at):
    database = schema_at("0027")
    run(
        database,
        f"INSERT INTO projects (id, project_number, is_doc_ged) VALUES ('{PROJECT}', '77GT.19.0220', false)",
        f"INSERT INTO sites (id, project_id) VALUES ('{SITE}', '{PROJECT}')",
        f"INSERT INTO surveys (id, site_id) VALUES ('{SURVEY}', '{SITE}')",
        f"""INSERT INTO correction_sites (id, project_id, longitude, latitude, valid, a_envoyer, horodatage, user_email, horodatage_correction)
            VALUES ('{SITE}', '{PROJECT}', 2.35, 48.85, true, false, NULL, 'agent@fondasol.fr', '2026-10-01T08:00:00+00:00')""",
    )
    return database


def test_surveys_get_fondasol_flag_true_by_default_contractor_and_file_url(before_0028):
    command.upgrade(ALEMBIC, "0028")

    assert rows(before_0028, "SELECT is_survey_fondasol, contractor, file_url FROM surveys") == [(True, None, None)]
    run(before_0028, f"UPDATE surveys SET is_survey_fondasol = false, contractor = 'Forages du Sud', file_url = '/depot/sp2.pdf' WHERE id = '{SURVEY}'")
    assert rows(before_0028, "SELECT is_survey_fondasol, contractor, file_url FROM surveys") == [(False, "Forages du Sud", "/depot/sp2.pdf")]
    with pytest.raises(DBAPIError):
        run(before_0028, f"UPDATE surveys SET is_survey_fondasol = NULL WHERE id = '{SURVEY}'")


def test_sites_get_an_optional_uuid_for_provided_external_data_and_no_quote(before_0028):
    command.upgrade(ALEMBIC, "0028")

    assert rows(before_0028, "SELECT provided_external_data_id FROM sites") == [(None,)]
    run(before_0028, f"UPDATE sites SET provided_external_data_id = 'c3b8a526-c399-4c9e-86dc-5cafcf9595a2' WHERE id = '{SITE}'")
    with pytest.raises(DBAPIError):
        run(before_0028, f"UPDATE sites SET provided_external_data_id = 'pas-un-uuid' WHERE id = '{SITE}'")
    assert "quote_id" not in columns(before_0028, "sites")
    assert not table_exists(before_0028, "quotes")


def test_correction_sites_becomes_geolocation_correction_history_and_keeps_its_rows(before_0028):
    command.upgrade(ALEMBIC, "0028")

    assert not table_exists(before_0028, "correction_sites")
    assert columns(before_0028, "geolocation_correction_history") == [
        "id", "project_id", "longitude", "latitude", "horodatage", "id_user", "user_email", "site_id", "survey_id",
    ]
    [(identifier, site_id, survey_id, longitude, recorded_at, email)] = rows(
        before_0028, "SELECT id::text, site_id, survey_id, longitude::float8, horodatage::text, user_email FROM geolocation_correction_history"
    )
    assert len(identifier) == 36 and identifier != SITE
    assert (site_id, survey_id, longitude, recorded_at, email) == (SITE, None, 2.35, "2026-10-01 08:00:00+00", "agent@fondasol.fr")


def test_geolocation_correction_history_requires_a_known_site_and_follows_its_site_and_survey(before_0028):
    command.upgrade(ALEMBIC, "0028")
    run(
        before_0028,
        "DELETE FROM geolocation_correction_history",
        f"INSERT INTO geolocation_correction_history (site_id, survey_id, longitude, latitude) VALUES ('{SITE}', '{SURVEY}', 2.36, 48.86)",
    )

    [(has_id, has_date)] = rows(before_0028, "SELECT id IS NOT NULL, horodatage IS NOT NULL FROM geolocation_correction_history")
    assert (has_id, has_date) == (True, True)
    for missing in ("INSERT INTO geolocation_correction_history (longitude) VALUES (2.3)", "INSERT INTO geolocation_correction_history (site_id) VALUES ('inconnu')"):
        with pytest.raises(DBAPIError):
            run(before_0028, missing)
    with pytest.raises(DBAPIError):
        run(before_0028, f"INSERT INTO geolocation_correction_history (site_id, survey_id) VALUES ('{SITE}', 'sondage-inconnu')")

    run(before_0028, f"DELETE FROM surveys WHERE id = '{SURVEY}'")
    assert rows(before_0028, "SELECT count(*) FROM geolocation_correction_history") == [(0,)]
    run(before_0028, f"INSERT INTO geolocation_correction_history (site_id) VALUES ('{SITE}')", f"DELETE FROM sites WHERE id = '{SITE}'")
    assert rows(before_0028, "SELECT count(*) FROM geolocation_correction_history") == [(0,)]
    indexes = {row[0] for row in rows(before_0028, "SELECT indexname FROM pg_indexes WHERE tablename = 'geolocation_correction_history'")}
    assert {"idx_geolocation_correction_history_site", "idx_geolocation_correction_history_survey"} <= indexes


def test_downgrade_brings_back_correction_sites_with_the_site_number_as_id(before_0028):
    command.upgrade(ALEMBIC, "0028")
    command.downgrade(ALEMBIC, "0027")

    assert not table_exists(before_0028, "geolocation_correction_history")
    assert set(columns(before_0028, "correction_sites")) == {
        "id", "project_id", "longitude", "latitude", "valid", "a_envoyer", "horodatage", "id_user", "user_email", "horodatage_correction",
    }
    assert rows(before_0028, "SELECT id, user_email FROM correction_sites") == [(SITE, "agent@fondasol.fr")]
    assert not {"is_survey_fondasol", "contractor", "file_url"} & set(columns(before_0028, "surveys"))
    assert "provided_external_data_id" not in columns(before_0028, "sites")
