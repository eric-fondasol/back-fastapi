from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")


def em_nullable(database):
    with database.connect() as connection:
        return connection.execute(
            text("SELECT is_nullable FROM information_schema.columns WHERE table_name = 'pressures' AND column_name = 'em'")
        ).scalar()


def table_exists(database, name):
    with database.connect() as connection:
        return connection.execute(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": name}).scalar()


def test_em_becomes_optional_and_the_water_testing_table_is_created(schema_at):
    database = schema_at("0030")

    command.upgrade(ALEMBIC, "0031")

    assert em_nullable(database) == "YES"
    assert table_exists(database, "water_testing_parameters")
    with database.connect() as connection:
        assert connection.execute(
            text("SELECT column_default FROM information_schema.columns WHERE table_name = 'surveys' AND column_name = 'is_water_testing'")
        ).scalar() == "false"


def test_downgrade_restores_em_with_zero_for_missing_values(schema_at):
    database = schema_at("0031")
    with database.begin() as connection:
        connection.execute(text("INSERT INTO projects (id, project_number, is_doc_ged) VALUES ('p', 'P', false)"))
        connection.execute(text("INSERT INTO sites (id, project_id) VALUES ('s', 'p')"))
        connection.execute(text("INSERT INTO surveys (id, site_id) VALUES ('sv', 's')"))
        connection.execute(text("INSERT INTO pressures (id, survey_id, depth, em, pl) VALUES ('m', 'sv', 1, NULL, 0.5)"))

    command.downgrade(ALEMBIC, "0030")

    assert em_nullable(database) == "NO"
    assert not table_exists(database, "water_testing_parameters")
    with database.connect() as connection:
        assert connection.execute(text("SELECT em FROM pressures WHERE id = 'm'")).scalar() == 0
