from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

LAYER = "SELECT code, kind, url, legend_url, params ->> 'color', params -> 'classes' ->> 'property', min_zoom::int, description_fr FROM catalog_layers WHERE code = 'fr-georisques-icpe'"

WMS = "SELECT kind, url, legend_url, params, min_zoom::int, description_fr FROM catalog_layers WHERE code = 'fr-georisques-icpe'"

TABLE = "SELECT to_regclass('icpe_sites') IS NOT NULL"

COLUMNS = "SELECT count(*) FROM information_schema.columns WHERE table_name = 'icpe_sites'"


def rows(database, query):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def test_the_icpe_layer_leaves_the_wms_for_its_own_table(schema_at):
    database = schema_at("0054")

    command.upgrade(ALEMBIC, "0055")

    description = "Installations classées pour la protection de l'environnement : usines (dont Seveso), carrières, éoliennes, élevages."
    assert rows(database, LAYER) == [("fr-georisques-icpe", "icpe", None, None, "#969696", "legende", 11, description)]
    assert rows(database, TABLE) == [(True,)]
    assert rows(database, COLUMNS) == [(26,)]


def test_downgrade_brings_back_the_wms_as_it_was_and_drops_the_table(schema_at):
    database = schema_at("0054")
    before = rows(database, WMS)
    command.upgrade(ALEMBIC, "0055")

    command.downgrade(ALEMBIC, "0054")

    assert rows(database, WMS) == before
    assert rows(database, TABLE) == [(False,)]
