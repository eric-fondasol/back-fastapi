from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

RELAYED = "SELECT code FROM catalog_layers WHERE (params ->> 'relayed')::boolean IS TRUE AND country = 'ca' ORDER BY code"
SIGEOM = "SELECT DISTINCT params ->> 'version' FROM catalog_layers WHERE url LIKE '%IDS_SGM_WMS%'"
LIDAR = [
    ("ca-qc-mrnf-courbes-niveau-lidar-10m",),
    ("ca-qc-mrnf-courbes-niveau-lidar-1m",),
    ("ca-qc-mrnf-courbes-niveau-lidar-5m",),
    ("ca-qc-mrnf-hydro-surfacique-lidar",),
    ("ca-qc-mrnf-lits-ecoulement-lidar",),
]
SIGEOM_LAYERS = [
    ("ca-qc-mrnf-geologie-regionale",),
    ("ca-qc-mrnf-provinces-geologiques",),
    ("ca-qc-mrnf-zones-morpho-sedimentologiques",),
    ("ca-qc-mrnf-zones-morpho-sedimentologiques-generales",),
]


def rows(database, query):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def test_the_sigeom_layers_are_relayed_in_addition_to_the_lidar_layers(schema_at):
    database = schema_at("0043")

    command.upgrade(ALEMBIC, "0044")

    assert rows(database, RELAYED) == sorted(LIDAR + SIGEOM_LAYERS)
    assert rows(database, SIGEOM) == [("1.1.1",)]


def test_downgrade_gives_the_sigeom_layers_back_to_the_browser(schema_at):
    database = schema_at("0044")

    command.downgrade(ALEMBIC, "0043")

    assert rows(database, RELAYED) == LIDAR
