from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

LAYERS = """
    SELECT code, kind, url, legend_url, params, min_zoom::int
    FROM catalog_layers WHERE code IN ('fr-georisques-casias-points', 'fr-georisques-casias-polygones') ORDER BY code
"""

TABLE = "SELECT to_regclass('casias_sites') IS NOT NULL"

COLUMNS = "SELECT count(*) FROM information_schema.columns WHERE table_name = 'casias_sites'"


def rows(database, query):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def legend(layer):
    return f"https://georisques.gouv.fr/services?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetLegendGraphic&FORMAT=image/png&LAYER={layer}&SLD_VERSION=1.1.0"


def test_the_casias_layers_leave_the_wms_for_their_own_table(schema_at):
    database = schema_at("0047")

    command.upgrade(ALEMBIC, "0048")

    assert rows(database, LAYERS) == [
        ("fr-georisques-casias-points", "casias", None, None, {"color": "#4884cc", "outline": "#3f3f3f", "symbol": "point"}, 13),
        ("fr-georisques-casias-polygones", "casias", None, None, {"color": "#4884cc"}, 12),
    ]
    assert rows(database, TABLE) == [(True,)]
    assert rows(database, COLUMNS) == [(24,)]


def test_downgrade_brings_back_the_wms_and_drops_the_table(schema_at):
    database = schema_at("0048")

    command.downgrade(ALEMBIC, "0047")

    wms = {"format": "image/png", "version": "1.3.0"}
    assert rows(database, LAYERS) == [
        ("fr-georisques-casias-points", "wms", "https://georisques.gouv.fr/services", legend("SSP_ETS_GE_POINT"), {**wms, "layers": "SSP_ETS_GE_POINT"}, 12),
        (
            "fr-georisques-casias-polygones",
            "wms",
            "https://georisques.gouv.fr/services",
            legend("SSP_ETS_GE_POLYGON"),
            {**wms, "layers": "SSP_ETS_GE_POLYGON"},
            12,
        ),
    ]
    assert rows(database, TABLE) == [(False,)]
