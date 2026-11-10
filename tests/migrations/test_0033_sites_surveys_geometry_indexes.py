from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")
INDEXES = ("idx_sites_geometry", "idx_surveys_geometry")


def geometry_indexes(database):
    with database.connect() as connection:
        rows = connection.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE indexname = ANY(:names)"), {"names": list(INDEXES)}
        ).all()
    return {name: definition for name, definition in rows}


def test_gist_indexes_are_created_on_the_geometry_of_sites_and_surveys(schema_at):
    database = schema_at("0032")

    command.upgrade(ALEMBIC, "0033")

    indexes = geometry_indexes(database)
    assert set(indexes) == set(INDEXES)
    assert "USING gist (geometry)" in indexes["idx_sites_geometry"]
    assert "ON public.surveys USING gist (geometry)" in indexes["idx_surveys_geometry"]


def test_upgrade_keeps_indexes_already_created_by_hand(schema_at):
    database = schema_at("0032")
    with database.begin() as connection:
        connection.execute(text("CREATE INDEX idx_sites_geometry ON public.sites USING gist (geometry)"))

    command.upgrade(ALEMBIC, "0033")

    assert set(geometry_indexes(database)) == set(INDEXES)


def test_downgrade_removes_the_geometry_indexes_and_keeps_the_geography_ones(schema_at):
    database = schema_at("0033")

    command.downgrade(ALEMBIC, "0032")

    assert geometry_indexes(database) == {}
    with database.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM pg_indexes WHERE indexname IN ('idx_sites_geography', 'idx_surveys_geography')")).scalar() == 2
