"""Réponse à « Avez-vous analysé votre fuseau ? », enregistrée avec chaque version d'enquête
(US-INVESTIGATIONS-11 du front). Vide quand la question n'a pas été posée.
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE saved_page_versions ADD COLUMN IF NOT EXISTS fuseau_analysis text
            CONSTRAINT saved_page_versions_fuseau_analysis CHECK (
                fuseau_analysis IN ('sold_a00196', 'cannot_optimize', 'later', 'not_suitable')
            )
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE saved_page_versions DROP COLUMN IF EXISTS fuseau_analysis")
