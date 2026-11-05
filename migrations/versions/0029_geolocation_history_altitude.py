"""Ancienne altitude dans geolocation_correction_history (décision du responsable du projet du 05/11/2026).

Chaque ligne garde la position et l'altitude d'un site ou d'un sondage juste avant sa modification.
Une ancienne position ou altitude absente (objet jamais positionné, ou marqué non géolocalisable) reste
à NULL : pas de colonne de motif, le motif actuel étant dans surveys et projects.
"""

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE geolocation_correction_history ADD COLUMN altitude float8")


def downgrade() -> None:
    op.execute("ALTER TABLE geolocation_correction_history DROP COLUMN altitude")
