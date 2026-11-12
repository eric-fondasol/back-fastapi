"""Catégorie parente « Eaux » pour « Eau - surface » et « Eau - souterraine » (demande du responsable du projet du
12/11/2026) : le panneau Couches du front montre « Eaux » comme une section repliable qui contient les deux
catégories, elles aussi repliables.

layer_categories.parent_id existe depuis la 0019 (deux niveaux au plus). « Eaux » prend la place de
« Eau - surface » parmi les catégories de premier niveau (position 4) ; les deux catégories d'eau gardent leur
ordre entre elles, et les couches restent rattachées aux catégories d'eau, pas à « Eaux ».

Une catégorie d'eau absente fait échouer la migration : une base au catalogue vide (constaté le 12/11/2026 sur
la base fondasol de recette) doit être signalée, pas laissée en l'état sans erreur.

Retour arrière : les deux catégories d'eau redeviennent de premier niveau, « Eaux » est supprimée.
"""

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

PARENT = "eaux"
CHILDREN = ["eau-surface", "eau-souterraine"]


class MissingCategory(Exception):
    pass


def upgrade() -> None:
    seed(op.get_bind())


# Séparée de upgrade pour que les tests, qui vident les tables, puissent la rejouer.
def seed(connection: sa.Connection) -> None:
    found = connection.execute(
        sa.text("SELECT count(*) FROM layer_categories WHERE code = ANY(:children)"), {"children": CHILDREN}
    ).scalar()
    if found != len(CHILDREN):
        raise MissingCategory(f"Catégories {', '.join(CHILDREN)} attendues dans layer_categories : catalogue incomplet")
    connection.execute(
        sa.text(
            """
            INSERT INTO layer_categories (code, label_fr, label_en, position)
            SELECT :parent, 'Eaux', 'Water', min(position) FROM layer_categories WHERE code = ANY(:children)
            ON CONFLICT (code) DO NOTHING
            """
        ),
        {"parent": PARENT, "children": CHILDREN},
    )
    connection.execute(
        sa.text(
            """
            UPDATE layer_categories
            SET parent_id = (SELECT id FROM layer_categories WHERE code = :parent), updated_at = now()
            WHERE code = ANY(:children)
            """
        ),
        {"parent": PARENT, "children": CHILDREN},
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE layer_categories SET parent_id = NULL, updated_at = now() WHERE code = ANY(:children)"),
        {"children": CHILDREN},
    )
    connection.execute(sa.text("DELETE FROM layer_categories WHERE code = :parent"), {"parent": PARENT})
