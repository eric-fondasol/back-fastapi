from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

LAYERS = """
    SELECT code, kind, url, legend_url, params, min_zoom::int
    FROM catalog_layers
    WHERE code IN ('fr-georisques-pollution-instruction-points', 'fr-georisques-pollution-instruction-polygones') ORDER BY code
"""

TABLE = "SELECT to_regclass('basol_sites') IS NOT NULL"

COLUMNS = "SELECT count(*) FROM information_schema.columns WHERE table_name = 'basol_sites'"


def rows(database, query):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def legend(layer):
    return f"https://georisques.gouv.fr/services?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetLegendGraphic&FORMAT=image/png&LAYER={layer}&SLD_VERSION=1.1.0"


def test_the_basol_layers_leave_the_wms_for_their_own_table(schema_at):
    database = schema_at("0050")

    command.upgrade(ALEMBIC, "0051")

    assert rows(database, LAYERS) == [
        ("fr-georisques-pollution-instruction-points", "basol", None, None, {"color": "#d7301f", "outline": "#3f3f3f", "symbol": "point"}, 12),
        ("fr-georisques-pollution-instruction-polygones", "basol", None, None, {"color": "#d7301f"}, 12),
    ]
    assert rows(database, TABLE) == [(True,)]
    assert rows(database, COLUMNS) == [(26,)]


def test_downgrade_brings_back_the_wms_and_drops_the_table(schema_at):
    database = schema_at("0051")

    command.downgrade(ALEMBIC, "0050")

    wms = {"format": "image/png", "version": "1.3.0"}
    assert rows(database, LAYERS) == [
        (
            "fr-georisques-pollution-instruction-points",
            "wms",
            "https://georisques.gouv.fr/services",
            legend("SSP_INSTR_GE_POINT"),
            {**wms, "layers": "SSP_INSTR_GE_POINT"},
            12,
        ),
        (
            "fr-georisques-pollution-instruction-polygones",
            "wms",
            "https://georisques.gouv.fr/services",
            legend("SSP_INSTR_GE_POLYGONE"),
            {**wms, "layers": "SSP_INSTR_GE_POLYGONE"},
            12,
        ),
    ]
    assert rows(database, TABLE) == [(False,)]
