from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

COLORS = """
SELECT entry ->> 'value', entry ->> 'color', entry -> 'label' ->> 'fr'
FROM catalog_layers, jsonb_array_elements(params -> 'classes' -> 'values') AS entry
WHERE code = :code
ORDER BY entry ->> 'value'
"""


def colors(database, code):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(COLORS), {"code": code})]


def test_the_protection_areas_get_distinct_colors_and_keep_their_labels(schema_at):
    database = schema_at("0044")

    command.upgrade(ALEMBIC, "0045")

    assert colors(database, "ca-qc-aires-protection-eau-souterraine") == [
        ("1", "#d7191c", "Immédiate"),
        ("2", "#ff7f00", "Intermédiaire bactériologique"),
        ("3", "#ffd400", "Intermédiaire virologique"),
        ("4", "#1f78b4", "Éloignée"),
    ]
    assert colors(database, "ca-qc-aires-protection-eau-surface") == [("1", "#d7191c", "Immédiate"), ("2", "#1b9e77", "Intermédiaire")]


def test_downgrade_gives_back_the_colors_of_the_0038(schema_at):
    database = schema_at("0045")

    command.downgrade(ALEMBIC, "0044")

    assert [color for _, color, _ in colors(database, "ca-qc-aires-protection-eau-souterraine")] == ["#e60000", "#ff6b00", "#ff00c5", "#a900e6"]
    assert [color for _, color, _ in colors(database, "ca-qc-aires-protection-eau-surface")] == ["#e60000", "#ff6b00"]
