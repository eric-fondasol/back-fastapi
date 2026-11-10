from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

NEW_CANADA = """
    SELECT l.code, c.code, l.params ->> 'layers', l.params ->> 'version', l.legend_url IS NOT NULL
    FROM catalog_layers l JOIN layer_categories c ON c.id = l.category_id
    WHERE l.country = 'ca' AND l.code LIKE 'ca-qc-mrnf-%'
    ORDER BY c.position, l.position
"""

LAYERS_AFTER_A_NEW_ONE = """
    SELECT older.code
    FROM catalog_layers new JOIN catalog_layers older ON older.category_id = new.category_id
    WHERE new.code LIKE 'ca-qc-mrnf-%' AND older.code NOT LIKE 'ca-qc-mrnf-%' AND older.position >= new.position
"""

CANADA = "SELECT code FROM catalog_layers WHERE country = 'ca' ORDER BY code"

SIGEOM_LEGEND = "SELECT legend_url FROM catalog_layers WHERE code = 'ca-qc-mrnf-provinces-geologiques'"


def rows(database, query):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def test_the_quebec_layers_join_their_categories_after_the_existing_ones(schema_at):
    database = schema_at("0033")

    command.upgrade(ALEMBIC, "0034")

    assert rows(database, NEW_CANADA) == [
        ("ca-qc-mrnf-geologie-regionale", "geologie", "SGM:Geologie_regionale", "1.1.1", False),
        ("ca-qc-mrnf-zones-morpho-sedimentologiques", "geologie", "SGM:Zones_morpho_sedimentologiques", "1.1.1", False),
        (
            "ca-qc-mrnf-zones-morpho-sedimentologiques-generales",
            "geologie",
            "SGM:Zones_morpho_sedimentologiques_qc",
            "1.1.1",
            False,
        ),
        ("ca-qc-mrnf-provinces-geologiques", "geologie", "SGM:Provinces_geologiques", "1.1.1", True),
        ("ca-qc-mrnf-courbes-niveau-lidar-1m", "topographie", "courbes_niveau_1m", "1.3.0", False),
        ("ca-qc-mrnf-courbes-niveau-lidar-5m", "topographie", "courbes_niveau_5m", "1.3.0", False),
        ("ca-qc-mrnf-courbes-niveau-lidar-10m", "topographie", "courbes_niveau_10m", "1.3.0", False),
        ("ca-qc-mrnf-topo-20k", "topographie", "BDTQ-20K", "1.3.0", False),
        ("ca-qc-mrnf-lits-ecoulement-lidar", "eau-surface", "hydrolidar_lits", "1.3.0", True),
        ("ca-qc-mrnf-hydro-surfacique-lidar", "eau-surface", "hydrolidar_surfac", "1.3.0", True),
    ]
    assert rows(database, LAYERS_AFTER_A_NEW_ONE) == []
    assert rows(database, SIGEOM_LEGEND) == [
        (
            "https://servicesvectoriels.atlas.gouv.qc.ca/IDS_SGM_WMS/service.svc/get?SERVICE=WMS&VERSION=1.1.1"
            "&REQUEST=GetLegendGraphic&FORMAT=image/png&LAYER=SGM:Provinces_geologiques&SLD_VERSION=1.1.0",
        )
    ]


def test_downgrade_removes_the_new_layers_and_keeps_the_older_quebec_ones(schema_at):
    database = schema_at("0034")

    command.downgrade(ALEMBIC, "0033")

    assert rows(database, CANADA) == [("ca-cadastre-lots",), ("ca-cptaq-demandes",)]
