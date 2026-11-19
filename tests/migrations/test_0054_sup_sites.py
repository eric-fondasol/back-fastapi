from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

LAYER = "SELECT code, kind, url, legend_url, params, min_zoom::int, max_zoom::int FROM catalog_layers WHERE code = 'fr-georisques-sup'"

ENVIRONMENT = """
    SELECT l.code FROM catalog_layers l JOIN layer_categories c ON c.id = l.category_id
    WHERE c.code = 'environnement' ORDER BY l.position, l.code
"""

POSITIONS = """
    SELECT count(*) = count(DISTINCT l.position) FROM catalog_layers l JOIN layer_categories c ON c.id = l.category_id
    WHERE c.code = 'environnement'
"""

TABLE = "SELECT to_regclass('sup_sites') IS NOT NULL"

COLUMNS = "SELECT count(*) FROM information_schema.columns WHERE table_name = 'sup_sites'"


def rows(database, query):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def test_the_sup_layer_is_created_right_after_the_sis_sectors_with_its_own_table(schema_at):
    database = schema_at("0053")
    before = [code for (code,) in rows(database, ENVIRONMENT)]

    command.upgrade(ALEMBIC, "0054")

    assert rows(database, LAYER) == [("fr-georisques-sup", "sup", None, None, {"color": "#018571"}, 12, 19)]
    sis = before.index("fr-georisques-sis")
    assert [code for (code,) in rows(database, ENVIRONMENT)] == [*before[: sis + 1], "fr-georisques-sup", *before[sis + 1 :]]
    assert rows(database, POSITIONS) == [(True,)]
    assert rows(database, TABLE) == [(True,)]
    assert rows(database, COLUMNS) == [(21,)]


def test_downgrade_removes_the_layer_and_the_table_and_closes_the_gap(schema_at):
    database = schema_at("0053")
    before = rows(database, ENVIRONMENT + "")
    command.upgrade(ALEMBIC, "0054")

    command.downgrade(ALEMBIC, "0053")

    assert rows(database, LAYER) == []
    assert rows(database, ENVIRONMENT) == before
    assert rows(database, TABLE) == [(False,)]
