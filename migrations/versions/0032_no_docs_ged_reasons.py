"""Motifs d'absence de documents GED (édition des détails du site, front, 09/11/2026).

no_docs_ged_reasons a été créée vide par la migration 0016 (« liste à fournir par le métier ») :
le métier demande « documents introuvables » et « sans suite », en plus de oui / non.
Le motif choisi est tracé dans docs_ged_changes.no_docs_ged_reason_id.

Retour arrière : les deux motifs sont retirés, et leurs traces perdent leur motif.
"""

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("INSERT INTO no_docs_ged_reasons (id, libelle) VALUES (1, 'Documents introuvables'), (2, 'Sans suite') ON CONFLICT (id) DO NOTHING")


def downgrade() -> None:
    op.execute("UPDATE docs_ged_changes SET no_docs_ged_reason_id = NULL WHERE no_docs_ged_reason_id IN (1, 2)")
    op.execute("DELETE FROM no_docs_ged_reasons WHERE id IN (1, 2)")
