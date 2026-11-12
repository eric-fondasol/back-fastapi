import importlib.util

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

STORED = """
    SELECT l.code, c.code, l.kind, l.url IS NULL
    FROM catalog_layers l JOIN layer_categories c ON c.id = l.category_id
    WHERE l.kind IN ('database', 'database-tiles')
    ORDER BY l.code
"""

TABLES = """
    SELECT tablename FROM pg_tables
    WHERE schemaname = 'public' AND tablename IN ('catalog_layer_features', 'catalog_layer_legends', 'catalog_layer_tiles')
    ORDER BY tablename
"""


def rows(database, query):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def test_the_seven_stored_layers_arrive_without_address_with_their_tables(schema_at):
    database = schema_at("0037")

    command.upgrade(ALEMBIC, "0038")

    assert rows(database, STORED) == [
        ("ca-mtl-carte-hydrogeologique", "eau-souterraine", "database-tiles", True),
        ("ca-mtl-depots-meubles-1426", "geologie", "database-tiles", True),
        ("ca-mtl-depots-meubles-1426-polygones", "geologie", "database", True),
        ("ca-mtl-isopiezes", "eau-souterraine", "database", True),
        ("ca-mtl-profondeur-roc-1427", "geologie", "database-tiles", True),
        ("ca-qc-aires-protection-eau-souterraine", "eau-souterraine", "database", True),
        ("ca-qc-aires-protection-eau-surface", "eau-surface", "database", True),
    ]
    assert rows(database, TABLES) == [("catalog_layer_features",), ("catalog_layer_legends",), ("catalog_layer_tiles",)]


def test_the_migration_can_be_replayed_on_a_database_that_already_has_it(schema_at):
    database = schema_at("0038")
    spec = importlib.util.spec_from_file_location("m0038", "migrations/versions/0038_catalog_database_layers.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with database.begin() as connection:
        module.create_tables(connection)
        module.seed(connection)

    assert len(rows(database, STORED)) == 7


def test_downgrade_removes_the_stored_layers_and_makes_the_address_mandatory_again(schema_at):
    database = schema_at("0038")

    command.downgrade(ALEMBIC, "0037")

    assert rows(database, STORED) == []
    assert rows(database, TABLES) == []
    assert rows(database, "SELECT is_nullable FROM information_schema.columns WHERE table_name = 'catalog_layers' AND column_name = 'url'") == [("NO",)]
