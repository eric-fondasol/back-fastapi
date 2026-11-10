"""Ajoute les réponses détaillées à la question sur l'analyse du fuseau."""

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE saved_page_versions DROP CONSTRAINT IF EXISTS saved_page_versions_fuseau_analysis")
    op.execute(
        """
        ALTER TABLE saved_page_versions ADD CONSTRAINT saved_page_versions_fuseau_analysis CHECK (
            fuseau_analysis IN (
                'sold_a00196', 'not_exploitable', 'investigation_mission', 'g2_pro_avp', 'imposed_program', 'later',
                'cannot_optimize', 'not_suitable'
            )
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE saved_page_versions
        SET fuseau_analysis = CASE
            WHEN fuseau_analysis = 'not_exploitable' THEN 'cannot_optimize'
            WHEN fuseau_analysis IN ('investigation_mission', 'g2_pro_avp', 'imposed_program') THEN 'not_suitable'
            ELSE fuseau_analysis
        END
        WHERE fuseau_analysis IN ('not_exploitable', 'investigation_mission', 'g2_pro_avp', 'imposed_program')
        """
    )
    op.execute("ALTER TABLE saved_page_versions DROP CONSTRAINT IF EXISTS saved_page_versions_fuseau_analysis")
    op.execute(
        """
        ALTER TABLE saved_page_versions ADD CONSTRAINT saved_page_versions_fuseau_analysis CHECK (
            fuseau_analysis IN ('sold_a00196', 'cannot_optimize', 'later', 'not_suitable')
        )
        """
    )