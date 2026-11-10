from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

RELAYED = "SELECT code FROM catalog_layers WHERE (params ->> 'relayed')::boolean IS TRUE AND country = 'ca' ORDER BY code"
VERSIONS = "SELECT DISTINCT params ->> 'version' FROM catalog_layers WHERE code LIKE 'ca-qc-mrnf-%lidar%'"


def rows(database, query):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def test_the_foret_ouverte_layers_are_relayed_and_the_other_quebec_layers_are_not(schema_at):
    database = schema_at("0035")

    command.upgrade(ALEMBIC, "0036")

    assert rows(database, RELAYED) == [
        ("ca-qc-mrnf-courbes-niveau-lidar-10m",),
        ("ca-qc-mrnf-courbes-niveau-lidar-1m",),
        ("ca-qc-mrnf-courbes-niveau-lidar-5m",),
        ("ca-qc-mrnf-hydro-surfacique-lidar",),
        ("ca-qc-mrnf-lits-ecoulement-lidar",),
    ]
    assert rows(database, VERSIONS) == [("1.3.0",)]


def test_downgrade_gives_the_layers_back_to_the_browser(schema_at):
    database = schema_at("0036")

    command.downgrade(ALEMBIC, "0035")

    assert rows(database, RELAYED) == []
    assert rows(database, VERSIONS) == [("1.3.0",)]
