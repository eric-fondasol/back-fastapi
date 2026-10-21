"""Style d'une couche fichier : couleur, épaisseur des traits, taille des points, champ en étiquette
(ADR-0039 du front). Vide = style par défaut, choisi par le front.
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_layers ADD COLUMN IF NOT EXISTS style jsonb NOT NULL DEFAULT '{}'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE user_layers DROP COLUMN IF EXISTS style")
