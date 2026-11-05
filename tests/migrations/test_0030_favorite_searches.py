from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")
TABLES = ["user_favorite_coordinates", "user_favorite_parcels", "user_favorite_quotes"]


def favorite_search_tables(database):
    with database.connect() as connection:
        return list(
            connection.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name = ANY(:names) ORDER BY 1"),
                {"names": TABLES},
            ).scalars()
        )


def test_the_three_search_favorite_tables_are_created(schema_at):
    database = schema_at("0029")

    command.upgrade(ALEMBIC, "0030")

    assert favorite_search_tables(database) == TABLES


def test_downgrade_removes_them(schema_at):
    database = schema_at("0030")

    command.downgrade(ALEMBIC, "0029")

    assert favorite_search_tables(database) == []
