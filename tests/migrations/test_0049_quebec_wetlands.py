from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

LAYER = """
    SELECT c.code, l.country, l.kind, l.url, l.legend_url, l.params -> 'classes' ->> 'property', l.params ->> 'color',
           l.min_zoom::int, l.max_zoom::int
    FROM catalog_layers l JOIN layer_categories c ON c.id = l.category_id
    WHERE l.code = 'ca-qc-milieux-humides'
"""

LAYERS_AFTER_IT = """
    SELECT older.code
    FROM catalog_layers new JOIN catalog_layers older ON older.category_id = new.category_id
    WHERE new.code = 'ca-qc-milieux-humides' AND older.code <> new.code AND older.position >= new.position
"""

TABLE = "SELECT to_regclass('quebec_wetlands') IS NOT NULL, to_regclass('quebec_wetland_classes') IS NOT NULL"

CLASSES = "SELECT code, color, label_fr, position FROM quebec_wetland_classes ORDER BY position"

FOREIGN_KEY = """
    SELECT count(*) FROM information_schema.referential_constraints r
    JOIN information_schema.table_constraints t ON t.constraint_name = r.constraint_name
    WHERE t.table_name = 'quebec_wetlands'
"""

PARAMS = "SELECT params FROM catalog_layers WHERE code = 'ca-qc-milieux-humides'"

COLUMNS = "SELECT count(*) FROM information_schema.columns WHERE table_name = 'quebec_wetlands'"


def rows(database, query):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def test_the_wetlands_layer_joins_surface_water_last_with_its_own_table(schema_at):
    database = schema_at("0048")

    command.upgrade(ALEMBIC, "0049")

    assert rows(database, LAYER) == [("eau-surface", "ca", "wetlands", None, None, None, "#97c919", 12, 19)]
    assert rows(database, PARAMS) == [({"color": "#97c919", "fillOpacity": 0.5},)]
    assert rows(database, LAYERS_AFTER_IT) == []
    assert rows(database, TABLE) == [(True, True)]
    assert rows(database, COLUMNS) == [(31,)]
    assert rows(database, FOREIGN_KEY) == [(1,)]
    classes = rows(database, CLASSES)
    assert [code for code, *_ in classes] == ["BG", "FN", "TB", "ME", "MS", "PH", "EP"]
    assert classes[3] == ("ME", "#55ff00", "Marécage", 4)


def test_downgrade_removes_the_layer_and_drops_the_table(schema_at):
    database = schema_at("0049")

    command.downgrade(ALEMBIC, "0048")

    assert rows(database, LAYER) == []
    assert rows(database, TABLE) == [(False, False)]
