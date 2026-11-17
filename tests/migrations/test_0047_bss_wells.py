from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

LAYER = """
    SELECT kind, url, legend_url, params -> 'classes' ->> 'property', jsonb_array_length(params -> 'classes' -> 'values')
    FROM catalog_layers WHERE code = 'fr-brgm-bss-tous-ouvrages'
"""

TABLE = "SELECT to_regclass('bss_wells') IS NOT NULL"

COLUMNS = "SELECT count(*) FROM information_schema.columns WHERE table_name = 'bss_wells'"


def rows(database, query):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def test_the_bss_layer_leaves_the_wms_for_its_own_table(schema_at):
    database = schema_at("0046")

    command.upgrade(ALEMBIC, "0047")

    assert rows(database, LAYER) == [("bss", None, None, "code_log", 6)]
    assert rows(database, TABLE) == [(True,)]
    assert rows(database, COLUMNS) == [(139,)]


def test_downgrade_brings_back_the_wms_and_drops_the_table(schema_at):
    database = schema_at("0047")

    command.downgrade(ALEMBIC, "0046")

    assert rows(database, LAYER) == [
        (
            "wms",
            "https://geoservices.brgm.fr/geologie",
            "https://geoservices.brgm.fr/geologie?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetLegendGraphic&FORMAT=image/png"
            "&LAYER=BSS_TOTAL_AVEC_LABEL&SLD_VERSION=1.1.0",
            None,
            None,
        )
    ]
    assert rows(database, TABLE) == [(False,)]
