from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

COLUMNS = """
    SELECT column_name, data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = :table AND column_name = 'kind'
"""


def kind_column(database, table):
    with database.connect() as connection:
        return connection.execute(text(COLUMNS), {"table": table}).all()


def run(database, *statements):
    with database.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def test_water_levels_automatic_gets_the_same_kind_column_as_water_levels_manual(schema_at):
    database = schema_at("0026")
    run(
        database,
        "INSERT INTO projects (id, project_number, is_doc_ged) VALUES ('5a02c2aa-2aa9-4b5b-9c93-20eb764d3ba7', '77GT.19.0220', false)",
        "INSERT INTO sites (id, project_id) VALUES ('77GT.19.0220', '5a02c2aa-2aa9-4b5b-9c93-20eb764d3ba7')",
        "INSERT INTO surveys (id, site_id) VALUES ('77GT.19.0220_PZ_1', '77GT.19.0220')",
        "INSERT INTO water_levels_automatic (survey_id, depth_m) VALUES ('77GT.19.0220_PZ_1', 3.2)",
    )
    assert kind_column(database, "water_levels_automatic") == []

    command.upgrade(ALEMBIC, "0027")

    assert kind_column(database, "water_levels_automatic") == kind_column(database, "water_levels_manual") == [("kind", "text", "YES", None)]
    with database.connect() as connection:
        assert connection.execute(text("SELECT depth_m, kind FROM water_levels_automatic")).all() == [(3.2, None)]


def test_downgrade_removes_the_kind_column_from_water_levels_automatic_only(schema_at):
    database = schema_at("0027")

    command.downgrade(ALEMBIC, "0026")

    assert kind_column(database, "water_levels_automatic") == []
    assert kind_column(database, "water_levels_manual") == [("kind", "text", "YES", None)]
