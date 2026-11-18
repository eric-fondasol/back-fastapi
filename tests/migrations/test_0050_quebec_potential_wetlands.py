from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

LAYER = """
    SELECT c.code, l.country, l.kind, l.url, l.legend_url, l.params, l.min_zoom::int, l.max_zoom::int
    FROM catalog_layers l JOIN layer_categories c ON c.id = l.category_id
    WHERE l.code = 'ca-qc-milieux-humides-potentiels'
"""

TABLES = "SELECT to_regclass('quebec_potential_wetlands') IS NOT NULL, to_regclass('quebec_potential_wetland_classes') IS NOT NULL"

OUTLINE = "SELECT count(*) FROM information_schema.columns WHERE table_name = 'quebec_wetland_classes' AND column_name = 'outline'"

CLASSES = "SELECT code, color, outline, label_fr, position FROM quebec_potential_wetland_classes ORDER BY position"

COLUMNS = "SELECT count(*) FROM information_schema.columns WHERE table_name = 'quebec_potential_wetlands'"


def rows(database, query):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def test_the_potential_wetlands_get_their_layer_their_tables_and_the_outline_of_each_class(schema_at):
    database = schema_at("0049")

    command.upgrade(ALEMBIC, "0050")

    assert rows(database, LAYER) == [("eau-surface", "ca", "potential-wetlands", None, None, {"color": "#cccccc", "fillOpacity": 0.5}, 12, 19)]
    assert rows(database, TABLES) == [(True, True)]
    assert rows(database, COLUMNS) == [(12,)]
    assert rows(database, OUTLINE) == [(1,)]
    classes = rows(database, CLASSES)
    assert len(classes) == 10
    assert classes[0] == ("Eau peu profonde", "#aebcff", "#6677cd", "Eau peu profonde", 1)
    assert classes[3] == ("Marécage", "#a3ff73", "#70a800", "Marécage indifférencié", 4)


def test_downgrade_removes_the_layer_the_tables_and_the_outline_column(schema_at):
    database = schema_at("0050")

    command.downgrade(ALEMBIC, "0049")

    assert rows(database, LAYER) == []
    assert rows(database, TABLES) == [(False, False)]
    assert rows(database, OUTLINE) == [(0,)]
