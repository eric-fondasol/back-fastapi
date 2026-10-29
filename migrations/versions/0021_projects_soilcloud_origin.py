"""Affaires : is_active_soilcloud (affaire active dans SoilCloud) et origin (provenance de l'affaire).

Demande du responsable du projet (29/10/2026), après le basculement v3. Colonnes créées sans reprise :
affaire.origine de l'entrepôt mêle textes libres et JSON (« REPRISE EN MASSE PMP »,
« {origine : Navision} », « {"origine":"Zoho"} »…) ; liste des valeurs à définir.
"""

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Valeur par défaut constante : colonne ajoutée sans réécrire les 303 000 affaires.
    op.execute(
        """
        ALTER TABLE projects
            ADD COLUMN is_active_soilcloud boolean NOT NULL DEFAULT false,
            ADD COLUMN origin varchar(255)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS origin, DROP COLUMN IF EXISTS is_active_soilcloud")
