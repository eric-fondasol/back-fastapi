"""Icônes des installations classées (ICPE) sur la carte et dans la légende (demande du responsable du projet du
19/11/2026, d'après la légende « Installations classées » de Géorisques ; ADR-0075 du front).

Chaque catégorie de params.classes (colonne legende) reçoit le nom d'une icône dessinée par le front (icon :
sevesoPlant, plant, windTurbine, cattle, poultry, pig, quarry) et la couleur de son fond, reprise de la légende de
Géorisques : usines en bleu (l'usine Seveso en plus grand), éolienne en jaune, élevages en vert, carrière en rose.
« Autres installations » n'a pas d'icône : elle reste un rond gris. Le front ne connaît que ces noms ; un nom
inconnu est ignoré et la catégorie redevient un rond de sa couleur.

Retour arrière : les classes de la migration 0055, sans icônes.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None

CODE = "fr-georisques-icpe"
OTHER = "#969696"


def category(value, color, label_fr, label_en, icon=None):
    entry = {"value": value, "color": color, "label": {"fr": label_fr, "en": label_en}}
    return entry if icon is None else {**entry, "icon": icon}


CLASSES = {
    "property": "legende",
    "values": [
        category("Usine Seveso", "#4a6bf7", "Usine Seveso", "Seveso plant", "sevesoPlant"),
        category("Usine non Seveso", "#4a6bf7", "Usine non Seveso", "Non-Seveso plant", "plant"),
        category("Eolienne", "#fdc200", "Éolienne", "Wind turbine", "windTurbine"),
        category("Elevage de bovin", "#00b063", "Élevage de bovins", "Cattle farm", "cattle"),
        category("Elevage de volaille", "#00b063", "Élevage de volailles", "Poultry farm", "poultry"),
        category("Elevage de porc", "#00b063", "Élevage de porcs", "Pig farm", "pig"),
        category("Carrière", "#f30067", "Carrière", "Quarry", "quarry"),
        category("Autres", OTHER, "Autres installations", "Other installations"),
    ],
}

CLASSES_BEFORE = {
    "property": "legende",
    "values": [
        category("Usine Seveso", "#d7191c", "Usine Seveso", "Seveso plant"),
        category("Usine non Seveso", "#fdae61", "Usine non Seveso", "Non-Seveso plant"),
        category("Carrière", "#8c510a", "Carrière", "Quarry"),
        category("Eolienne", "#2c7bb6", "Éolienne", "Wind turbine"),
        category("Elevage de porc", "#f781bf", "Élevage de porcs", "Pig farm"),
        category("Elevage de volaille", "#e6ab02", "Élevage de volailles", "Poultry farm"),
        category("Elevage de bovin", "#1a9641", "Élevage de bovins", "Cattle farm"),
        category("Autres", OTHER, "Autres installations", "Other installations"),
    ],
}


def _set_classes(connection: sa.Connection, classes: dict) -> None:
    connection.execute(
        sa.text("UPDATE catalog_layers SET params = jsonb_set(params, '{classes}', CAST(:classes AS jsonb)), updated_at = now() WHERE code = :code"),
        {"code": CODE, "classes": json.dumps(classes, ensure_ascii=False)},
    )


def upgrade() -> None:
    switch_to_icons(op.get_bind())


# Séparée de upgrade pour que les tests, qui vident les tables, puissent la rejouer.
def switch_to_icons(connection: sa.Connection) -> None:
    _set_classes(connection, CLASSES)


def downgrade() -> None:
    _set_classes(op.get_bind(), CLASSES_BEFORE)
