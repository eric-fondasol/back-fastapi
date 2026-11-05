"""Colonne `kind` sur water_levels_automatic, comme sur water_levels_manual (demande du responsable du
projet du 05/11/2026) : les deux tables de niveaux d'eau ont désormais les mêmes colonnes.

Texte libre et facultatif, sans contrainte ni valeur par défaut, à l'image de water_levels_manual.kind :
l'ajout ne réécrit pas les lignes existantes, qui restent à NULL.
"""

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE water_levels_automatic ADD COLUMN kind text")


def downgrade() -> None:
    op.execute("ALTER TABLE water_levels_automatic DROP COLUMN kind")
