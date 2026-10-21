"""Trace de la saisie manuelle de is_doc_ged : qui (adresse) et quand (UTC), depuis le panneau
Détails de l'affaire du front. Vides tant que la valeur n'a été écrite que par le script de la GED.
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_doc_ged_updated_by varchar(255) DEFAULT NULL")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_doc_ged_updated_at timestamp(0) without time zone DEFAULT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS is_doc_ged_updated_at")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS is_doc_ged_updated_by")
