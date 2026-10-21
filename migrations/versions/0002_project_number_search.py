"""Index de la recherche par n° d'affaire, sans tenir compte de la casse ni de la ponctuation.

« 95.gt.25 » doit trouver « 95GT.25.0159 » : la recherche compare le numéro réduit à ses lettres
majuscules et chiffres (queries.COMPACT_PROJECT_ID). text_pattern_ops permet à LIKE 'préfixe%'
d'utiliser l'index.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_projects_compact_id "
        "ON projects ((regexp_replace(upper(id), '[^A-Z0-9]', '', 'g')) text_pattern_ops)"
    )
    # Sans statistiques sur l'expression, le planificateur ignore l'index (constaté : 44 ms au lieu de 10).
    op.execute("ANALYZE projects")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_projects_compact_id")
