from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

COLUMNS = """
    SELECT table_name, column_name FROM information_schema.columns
    WHERE table_name IN ('penetrometer_tests', 'penetrometer_machine_types')
      AND column_name IN ('tip_mass', 'tip_section', 'penetration')
    ORDER BY table_name, column_name
"""


def columns(database):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(COLUMNS))]


def test_the_pv510_characteristics_are_added_to_the_test_and_the_machine_type(schema_at):
    database = schema_at("0040")

    command.upgrade(ALEMBIC, "0041")

    assert columns(database) == [
        ("penetrometer_machine_types", "penetration"),
        ("penetrometer_machine_types", "tip_mass"),
        ("penetrometer_machine_types", "tip_section"),
        ("penetrometer_tests", "penetration"),
        ("penetrometer_tests", "tip_mass"),
        ("penetrometer_tests", "tip_section"),
    ]


def test_downgrade_removes_only_the_added_columns(schema_at):
    database = schema_at("0041")

    command.downgrade(ALEMBIC, "0040")

    assert columns(database) == [("penetrometer_tests", "tip_section")]
