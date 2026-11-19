from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")

CLASSES = "SELECT params -> 'classes' FROM catalog_layers WHERE code = 'fr-georisques-icpe'"


def classes(database):
    with database.connect() as connection:
        return connection.execute(text(CLASSES)).scalar_one()


def test_each_icpe_category_gets_the_icon_of_the_georisques_legend_except_the_others(schema_at):
    database = schema_at("0055")

    command.upgrade(ALEMBIC, "0056")

    icons = {entry["value"]: (entry.get("icon"), entry["color"]) for entry in classes(database)["values"]}
    assert icons == {
        "Usine Seveso": ("sevesoPlant", "#4a6bf7"),
        "Usine non Seveso": ("plant", "#4a6bf7"),
        "Eolienne": ("windTurbine", "#fdc200"),
        "Elevage de bovin": ("cattle", "#00b063"),
        "Elevage de volaille": ("poultry", "#00b063"),
        "Elevage de porc": ("pig", "#00b063"),
        "Carrière": ("quarry", "#f30067"),
        "Autres": (None, "#969696"),
    }


def test_downgrade_brings_back_the_classes_without_icons(schema_at):
    database = schema_at("0055")
    before = classes(database)
    command.upgrade(ALEMBIC, "0056")

    command.downgrade(ALEMBIC, "0055")

    assert classes(database) == before
