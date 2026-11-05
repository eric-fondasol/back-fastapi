from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

ALTITUDE = """
    SELECT data_type, is_nullable, column_default FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'geolocation_correction_history' AND column_name = 'altitude'
"""


def altitude_column(database):
    with database.connect() as connection:
        return connection.execute(text(ALTITUDE)).all()


def test_the_history_keeps_an_optional_previous_altitude(schema_at):
    database = schema_at("0028")

    command.upgrade(ALEMBIC, "0029")

    assert altitude_column(database) == [("double precision", "YES", None)]


def test_downgrade_removes_the_previous_altitude(schema_at):
    database = schema_at("0029")

    command.downgrade(ALEMBIC, "0028")

    assert altitude_column(database) == []
