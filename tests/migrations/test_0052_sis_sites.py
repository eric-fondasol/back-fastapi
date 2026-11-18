from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

LAYER = "SELECT code, kind, url, legend_url, params, min_zoom::int FROM catalog_layers WHERE code = 'fr-georisques-sis'"

TABLE = "SELECT to_regclass('sis_sites') IS NOT NULL"

COLUMNS = "SELECT count(*) FROM information_schema.columns WHERE table_name = 'sis_sites'"

LEGEND = "https://georisques.gouv.fr/services?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetLegendGraphic&FORMAT=image/png&LAYER=SSP_CLASSIF_SIS_GE&SLD_VERSION=1.1.0"


def rows(database, query):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def test_the_sis_layer_leaves_the_wms_for_its_own_table(schema_at):
    database = schema_at("0051")

    command.upgrade(ALEMBIC, "0052")

    assert rows(database, LAYER) == [("fr-georisques-sis", "sis", None, None, {"color": "#7b3294"}, 12)]
    assert rows(database, TABLE) == [(True,)]
    assert rows(database, COLUMNS) == [(21,)]


def test_downgrade_brings_back_the_wms_and_drops_the_table(schema_at):
    database = schema_at("0052")

    command.downgrade(ALEMBIC, "0051")

    params = {"format": "image/png", "layers": "SSP_CLASSIF_SIS_GE", "version": "1.3.0"}
    assert rows(database, LAYER) == [("fr-georisques-sis", "wms", "https://georisques.gouv.fr/services", LEGEND, params, 12)]
    assert rows(database, TABLE) == [(False,)]
