from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

from tests.domains.projects.test_routes import add_project, add_survey

ALEMBIC = AlembicConfig("alembic.ini")

TYPES = """
    SELECT type, hammer_drop_height, hammer_mass, rod_mass, tip_mass, tip_section, anvil_mass, penetration
    FROM penetrometer_machine_types ORDER BY type
"""


def rows(database, query=TYPES):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def test_the_five_types_of_the_csv_are_added_with_the_drop_height_in_metres_and_the_accessories_summed(schema_at):
    database = schema_at("0041")

    command.upgrade(ALEMBIC, "0042")

    assert rows(database) == [
        ("DPH strasbourg", 0.5, 50, 5.62, 0.61, 20, 15.17, 10),
        ("DPL FONDASOL", 0.5, 10, 2.64, 0.23, 10, 4.62, 10),
        ("DPSHB SOCO 10", 0.75, 63.5, 5.62, 0.61, 20, 11.19, 10),
        ("DPSHB SOCO/SMRI", 0.75, 63.5, 5.62, 0.61, 20, 12.07, 10),
        ("DPSHB TECOINSA", 0.75, 63.5, 5.62, 0.61, 20, 15.17, 10),
    ]


def test_an_existing_type_of_the_same_name_takes_the_values_of_the_csv(schema_at):
    database = schema_at("0041")
    with database.begin() as connection:
        connection.execute(text("INSERT INTO penetrometer_machine_types (type, hammer_mass) VALUES ('DPL FONDASOL', 99)"))

    command.upgrade(ALEMBIC, "0042")

    assert rows(database, "SELECT type, hammer_mass FROM penetrometer_machine_types WHERE type = 'DPL FONDASOL'") == [("DPL FONDASOL", 10)]


def test_downgrade_keeps_a_type_used_by_a_test(schema_at):
    database = schema_at("0042")
    add_project(database, "AF.ET.16.0210")
    add_survey(database, "AF.ET.16.0210_PD_2", "AF.ET.16.0210")
    with database.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO penetrometer_tests (survey_id, machine_type_id) "
                "SELECT 'AF.ET.16.0210_PD_2', id FROM penetrometer_machine_types WHERE type = 'DPL FONDASOL'"
            )
        )

    command.downgrade(ALEMBIC, "0041")

    assert rows(database, "SELECT type FROM penetrometer_machine_types ORDER BY type") == [("DPL FONDASOL",)]
