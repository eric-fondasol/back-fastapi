import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")


def run(database, *statements):
    with database.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def rows(database, query):
    with database.connect() as connection:
        return connection.execute(text(query)).all()


@pytest.fixture
def before_0022(schema_at):
    database = schema_at("0021")
    run(
        database,
        "INSERT INTO projects (id, project_number, is_doc_ged) VALUES ('5a02c2aa-2aa9-4b5b-9c93-20eb764d3ba7', '77GT.19.0220', false)",
        "INSERT INTO sites (id, project_id) VALUES ('77GT.19.0220', '5a02c2aa-2aa9-4b5b-9c93-20eb764d3ba7')",
        "INSERT INTO surveys (id, site_id) VALUES ('77GT.19.0220_SP_2', '77GT.19.0220')",
    )
    return database


def test_referentiels_and_standards_start_with_the_requested_values(before_0022):
    command.upgrade(ALEMBIC, "0022")

    assert rows(before_0022, "SELECT code FROM referentiels ORDER BY position") == [("NGF",), ("LUREF",)]
    assert rows(before_0022, "SELECT code FROM standards ORDER BY position") == [("DTU 14.1",), ("Eurocode 7",)]


def test_a_referentiel_already_used_by_a_water_level_is_kept_and_an_unknown_one_is_refused(before_0022):
    run(
        before_0022,
        "INSERT INTO water_levels_manual (survey_id, referentiel) VALUES ('77GT.19.0220_SP_2', 'TN'), ('77GT.19.0220_SP_2', 'NGF')",
        "INSERT INTO water_levels_automatic (survey_id, referentiel) VALUES ('77GT.19.0220_SP_2', NULL)",
    )

    command.upgrade(ALEMBIC, "0022")

    assert rows(before_0022, "SELECT code, label_fr FROM referentiels WHERE code = 'TN'") == [("TN", "TN")]
    with pytest.raises(Exception, match="foreign key"):
        run(before_0022, "INSERT INTO water_levels_automatic (survey_id, referentiel) VALUES ('77GT.19.0220_SP_2', 'XX')")


def test_reference_levels_go_with_their_survey_and_require_a_known_referentiel_and_standard(before_0022):
    command.upgrade(ALEMBIC, "0022")
    run(
        before_0022,
        """
        INSERT INTO gw_reference_levels (survey_id, site_id, eb_depth, eh_depth, ee_depth, eb_ref, eh_ref, ee_ref,
                                         referentiel, standard_id, structure)
        SELECT '77GT.19.0220_SP_2', '77GT.19.0220', 4.2, 2.1, 1.0, 108.3, 110.4, 111.5, 'NGF', id, 'Gymnase'
        FROM standards WHERE code = 'Eurocode 7'
        """,
    )

    for statement in (
        "INSERT INTO gw_reference_levels (survey_id, referentiel) VALUES ('77GT.19.0220_SP_2', 'XX')",
        "INSERT INTO gw_reference_levels (survey_id, standard_id) VALUES ('77GT.19.0220_SP_2', 999)",
    ):
        with pytest.raises(Exception, match="foreign key"):
            run(before_0022, statement)

    run(before_0022, "DELETE FROM surveys")
    assert rows(before_0022, "SELECT count(*) FROM gw_reference_levels") == [(0,)]


def test_a_penetrometer_test_points_to_its_machine_type_and_pressures_keep_their_symbols(before_0022):
    command.upgrade(ALEMBIC, "0022")
    run(
        before_0022,
        "INSERT INTO penetrometer_machine_types (type, hammer_mass, hammer_drop_height, rod_mass, anvil_mass) VALUES ('PDB', 64, 0.75, 6.3, 18)",
        """
        INSERT INTO penetrometer_tests (survey_id, machine_type_id)
        SELECT '77GT.19.0220_SP_2', id FROM penetrometer_machine_types WHERE type = 'PDB'
        """,
        "INSERT INTO pressures (id, survey_id, depth, em, pl, plsym, pf, pfsym) VALUES ('p1', '77GT.19.0220_SP_2', 3, 12, 2.5, '>', 1.8, '>')",
    )

    with pytest.raises(Exception, match="foreign key"):
        run(before_0022, "DELETE FROM penetrometer_machine_types")
    assert rows(before_0022, "SELECT plsym, pfsym FROM pressures") == [(">", ">")]


def test_the_migration_goes_back_to_0021(before_0022):
    command.upgrade(ALEMBIC, "0022")
    command.downgrade(ALEMBIC, "0021")

    tables = {name for (name,) in rows(before_0022, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    assert not tables & {"referentiels", "standards", "gw_reference_levels", "penetrometer_machine_types"}
    assert rows(before_0022, "SELECT count(*) FROM information_schema.columns WHERE table_name = 'pressures' AND column_name IN ('pfsym', 'plsym')") == [(0,)]
