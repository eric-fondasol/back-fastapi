from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

LAYER = "SELECT code, kind, url, legend_url, params, min_zoom::int FROM catalog_layers WHERE code = 'fr-georisques-etablissements-pollueurs'"

TABLE = "SELECT to_regclass('polluting_facilities') IS NOT NULL"

COLUMNS = "SELECT count(*) FROM information_schema.columns WHERE table_name = 'polluting_facilities'"

LEGEND = (
    "https://georisques.gouv.fr/services?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetLegendGraphic&FORMAT=image/png&LAYER=ETABLISSEMENTS_POLLUEURS&SLD_VERSION=1.1.0"
)


def rows(database, query):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def test_the_polluting_facilities_leave_the_wms_for_their_own_table(schema_at):
    database = schema_at("0052")

    command.upgrade(ALEMBIC, "0053")

    params = {"color": "#e08214", "outline": "#3f3f3f", "symbol": "point"}
    assert rows(database, LAYER) == [("fr-georisques-etablissements-pollueurs", "polluting-facilities", None, None, params, 9)]
    assert rows(database, TABLE) == [(True,)]
    assert rows(database, COLUMNS) == [(11,)]


def test_downgrade_brings_back_the_wms_and_drops_the_table(schema_at):
    database = schema_at("0053")

    command.downgrade(ALEMBIC, "0052")

    params = {"format": "image/png", "layers": "ETABLISSEMENTS_POLLUEURS", "version": "1.3.0"}
    assert rows(database, LAYER) == [("fr-georisques-etablissements-pollueurs", "wms", "https://georisques.gouv.fr/services", LEGEND, params, 9)]
    assert rows(database, TABLE) == [(False,)]
