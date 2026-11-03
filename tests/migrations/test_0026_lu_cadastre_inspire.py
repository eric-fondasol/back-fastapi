from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

CADASTRE = """
    SELECT url, params ->> 'layers', min_zoom, legend_url
    FROM catalog_layers WHERE code = 'lu-act-parcelles-cadastrales'
"""


def cadastre(database):
    with database.connect() as connection:
        return tuple(connection.execute(text(CADASTRE)).one())


def test_the_luxembourg_cadastre_moves_to_the_inspire_service_from_zoom_15_under_the_same_code(schema_at):
    database = schema_at("0025")

    command.upgrade(ALEMBIC, "0026")

    assert cadastre(database) == ("https://wms.inspire.geoportail.lu/geoserver/cp/wms", "CP.CadastralParcel", 15, None)


def test_downgrade_brings_back_the_opendata_layer(schema_at):
    database = schema_at("0026")

    command.downgrade(ALEMBIC, "0025")

    assert cadastre(database) == ("https://wmts1.geoportail.lu/opendata/service", "parcels", 13, None)
