from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

LUXEMBOURG = """
    SELECT l.code, c.code, l.params ->> 'layers'
    FROM catalog_layers l JOIN layer_categories c ON c.id = l.category_id
    WHERE l.country = 'lu'
    ORDER BY c.position, l.position
"""

LAYERS_AFTER_A_NEW_ONE = """
    SELECT older.code
    FROM catalog_layers new JOIN catalog_layers older ON older.category_id = new.category_id
    WHERE new.country = 'lu' AND new.code <> 'lu-geologie' AND older.country <> 'lu' AND older.position >= new.position
"""

GEOLOGY = "SELECT params ->> 'layers', attribution, min_zoom, max_zoom FROM catalog_layers WHERE code = 'lu-geologie'"


def rows(database, query):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def test_the_luxembourg_layers_join_their_categories_after_the_existing_ones(schema_at):
    database = schema_at("0024")

    command.upgrade(ALEMBIC, "0025")

    assert rows(database, LUXEMBOURG) == [
        ("lu-geologie", "geologie", "2167"),
        ("lu-act-parcelles-cadastrales", "cadastre", "parcels"),
        ("lu-act-orthophoto", "topographie", "ortho_latest"),
        ("lu-act-topo-5k", "topographie", "topo_5k"),
        ("lu-age-cours-eau", "eau-surface", "749"),
        ("lu-age-hq-extreme", "eau-surface", "3263"),
        ("lu-age-hq100", "eau-surface", "3262"),
        ("lu-age-hq10", "eau-surface", "3261"),
        ("lu-age-zps-rgd", "eau-souterraine", "573"),
        ("lu-age-geoth-admissibilite", "geothermie", "2396"),
        ("lu-aev-casipo", "environnement", "1362"),
    ]
    assert rows(database, LAYERS_AFTER_A_NEW_ONE) == []
    assert rows(database, GEOLOGY) == [("2167", "© Service géologique de l’État (PCH) – geoportail.lu", 9, 18)]


def test_downgrade_removes_the_new_layers_and_restores_the_geological_map(schema_at):
    database = schema_at("0025")

    command.downgrade(ALEMBIC, "0024")

    assert [code for code, *_ in rows(database, LUXEMBOURG)] == ["lu-geologie"]
    assert rows(database, GEOLOGY) == [("2167_1", "© geoportail.lu", None, None)]
