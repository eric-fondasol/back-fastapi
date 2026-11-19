import importlib.util

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

SUBCATEGORIES = """
    SELECT c.code, c.label_fr, c.label_en, p.code
    FROM layer_categories c JOIN layer_categories p ON p.id = c.parent_id
    WHERE p.code = 'environnement'
    ORDER BY c.position, c.code
"""

POLLUTION_LAYERS = """
    SELECT l.code, c.code
    FROM catalog_layers l JOIN layer_categories c ON c.id = l.category_id
    WHERE l.code LIKE 'fr-georisques-casias-%' OR l.code LIKE 'fr-georisques-pollution-instruction-%'
    ORDER BY c.position, l.position
"""

LABELS = """
    SELECT code, label_fr, label_en FROM catalog_layers
    WHERE code LIKE 'fr-georisques-casias-%' OR code LIKE 'fr-georisques-pollution-instruction-%'
    ORDER BY code
"""

ENVIRONMENT_LAYERS = """
    SELECT l.code FROM catalog_layers l JOIN layer_categories c ON c.id = l.category_id
    WHERE c.code = 'environnement' AND l.country = 'fr'
    ORDER BY l.position
"""


def rows(database, query):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def migration():
    spec = importlib.util.spec_from_file_location("m0057", "migrations/versions/0057_environment_pollution_subcategories.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_casias_and_former_basol_layers_move_into_their_own_subcategories_of_the_environment(schema_at):
    database = schema_at("0056")

    command.upgrade(ALEMBIC, "0057")

    assert rows(database, SUBCATEGORIES) == [
        ("casias", "CASIAS", "CASIAS", "environnement"),
        ("ex-basol", "ex-BASOL", "ex-BASOL", "environnement"),
    ]
    assert rows(database, POLLUTION_LAYERS) == [
        ("fr-georisques-casias-points", "casias"),
        ("fr-georisques-casias-polygones", "casias"),
        ("fr-georisques-pollution-instruction-points", "ex-basol"),
        ("fr-georisques-pollution-instruction-polygones", "ex-basol"),
    ]
    assert rows(database, LABELS) == [
        ("fr-georisques-casias-points", "Sites CASIAS (points)", "CASIAS sites (points)"),
        ("fr-georisques-casias-polygones", "Sites CASIAS (polygones)", "CASIAS sites (polygons)"),
        ("fr-georisques-pollution-instruction-points", "ex-BASOL (points)", "ex-BASOL (points)"),
        ("fr-georisques-pollution-instruction-polygones", "ex-BASOL (polygones)", "ex-BASOL (polygons)"),
    ]
    environment = [code for (code,) in rows(database, ENVIRONMENT_LAYERS)]
    assert "fr-georisques-sis" in environment
    assert not any(code.startswith(("fr-georisques-casias", "fr-georisques-pollution-instruction")) for code in environment)


def test_downgrade_puts_the_layers_back_in_the_environment_and_removes_the_subcategories(schema_at):
    database = schema_at("0057")

    command.downgrade(ALEMBIC, "0056")

    assert rows(database, SUBCATEGORIES) == []
    assert {category for (_, category) in rows(database, POLLUTION_LAYERS)} == {"environnement"}
    assert rows(database, LABELS)[2:] == [
        (
            "fr-georisques-pollution-instruction-points",
            "Pollution suspectée ou avérée - information de l'administration (points)",
            "Suspected or proven pollution - administration information (points)",
        ),
        (
            "fr-georisques-pollution-instruction-polygones",
            "Pollution suspectée ou avérée - information de l'administration (polygones)",
            "Suspected or proven pollution - administration information (polygons)",
        ),
    ]


def test_an_incomplete_catalog_makes_the_migration_fail_instead_of_doing_nothing(schema_at):
    database = schema_at("0056")
    with database.begin() as connection:
        connection.execute(text("DELETE FROM catalog_layers WHERE code = 'fr-georisques-casias-points'"))

    module = migration()

    with database.begin() as connection, pytest.raises(module.IncompleteCatalog):
        module.seed(connection)
