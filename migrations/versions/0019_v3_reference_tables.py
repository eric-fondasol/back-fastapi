"""Basculement v3, étape 6 : départements, catégories du catalogue, couches de l'utilisateur.

departments : code_service devient business_unit_codes (texte « 34GT|31GT » gardé ; table de liaison à trancher).
layer_categories : parent_id, pour les sous-catégories (deux niveaux au plus, contrôlé par le back).
user_layers : emprise d'un fichier (west, south, east, north) retirée, le back la calculera à l'import.

Pas de retour arrière : restaurer le dump pris avant le basculement.
"""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE departments RENAME COLUMN code_service TO business_unit_codes")

    op.execute("ALTER TABLE layer_categories ADD COLUMN parent_id uuid REFERENCES layer_categories (id) ON DELETE RESTRICT")
    op.execute("CREATE INDEX idx_layer_categories_parent ON layer_categories (parent_id, position)")

    op.execute("ALTER TABLE user_layers DROP COLUMN west, DROP COLUMN south, DROP COLUMN east, DROP COLUMN north")


def downgrade() -> None:
    raise RuntimeError("Basculement v3 sans retour arrière : restaurer le dump pris avant la migration 0014.")
