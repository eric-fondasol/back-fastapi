from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

WATER_FLOW = """
    SELECT c.code, l.country, l.kind, l.url, l.params ->> 'layers', l.params ->> 'version', l.params ? 'relayed',
           l.min_zoom, l.max_zoom, l.legend_url IS NOT NULL
    FROM catalog_layers l JOIN layer_categories c ON c.id = l.category_id
    WHERE l.code = 'ca-nrcan-nhn-water-flow'
"""

LAYERS_AFTER_IT = """
    SELECT older.code
    FROM catalog_layers new JOIN catalog_layers older ON older.category_id = new.category_id
    WHERE new.code = 'ca-nrcan-nhn-water-flow' AND older.code <> new.code AND older.position >= new.position
"""


def rows(database, query):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def test_the_water_flow_layer_joins_surface_water_last_and_is_requested_directly(schema_at):
    database = schema_at("0045")

    command.upgrade(ALEMBIC, "0046")

    assert rows(database, WATER_FLOW) == [
        (
            "eau-surface",
            "ca",
            "wms",
            "https://maps.geogratis.gc.ca/wms/hydro_network_en",
            "nhn:nhn:network:flowdirection_1",
            "1.3.0",
            False,
            12,
            19,
            True,
        )
    ]
    assert rows(database, LAYERS_AFTER_IT) == []


def test_downgrade_removes_the_water_flow_layer(schema_at):
    database = schema_at("0046")

    command.downgrade(ALEMBIC, "0045")

    assert rows(database, WATER_FLOW) == []
