import importlib.util

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

WATER = """
    SELECT c.code, c.position, p.code
    FROM layer_categories c LEFT JOIN layer_categories p ON p.id = c.parent_id
    WHERE c.code IN ('eaux', 'eau-surface', 'eau-souterraine')
    ORDER BY c.position, c.code
"""


def rows(database, query):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def migration():
    spec = importlib.util.spec_from_file_location("m0039", "migrations/versions/0039_water_parent_category.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_water_category_takes_the_place_of_its_first_child_and_holds_both(schema_at):
    database = schema_at("0038")

    command.upgrade(ALEMBIC, "0039")

    assert rows(database, WATER) == [
        ("eau-surface", 4, "eaux"),
        ("eaux", 4, None),
        ("eau-souterraine", 5, "eaux"),
    ]


def test_downgrade_puts_the_water_categories_back_at_the_first_level(schema_at):
    database = schema_at("0039")

    command.downgrade(ALEMBIC, "0038")

    assert rows(database, WATER) == [("eau-surface", 4, None), ("eau-souterraine", 5, None)]


def test_an_empty_catalog_makes_the_migration_fail_instead_of_doing_nothing(schema_at):
    database = schema_at("0039")
    with database.begin() as connection:
        connection.execute(text("TRUNCATE layer_categories CASCADE"))

    module = migration()

    with database.begin() as connection, pytest.raises(module.MissingCategory):
        module.seed(connection)
