"""Accès général d'une business unit aux recherches d'adresse sur tout le territoire.

Remplace services.full_access, retirée avec la table services par 0020 (droits de recherche réécrits
autour de business_units, décision du responsable du projet du 02/11/2026). Reprend les 10 codes qui
avaient cet accès dans la base locale (fondasol2, 02/11/2026).
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

FULL_ACCESS_CODES = ("54CO", "59CO", "84CO", "44CO", "GPCO", "GFCO", "DTRD", "SOLROC", "GFDT", "DTMG")


def upgrade() -> None:
    op.execute("ALTER TABLE business_units ADD COLUMN full_access boolean NOT NULL DEFAULT false")
    codes = ", ".join(f"'{code}'" for code in FULL_ACCESS_CODES)
    op.execute(f"UPDATE business_units SET full_access = true WHERE code IN ({codes})")


def downgrade() -> None:
    op.execute("ALTER TABLE business_units DROP COLUMN full_access")
