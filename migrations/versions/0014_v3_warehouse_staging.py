"""Basculement sur le schéma v3 (ADR-0048 du front), étape 1 : tables d'attente des données de l'entrepôt.

La v3 demande des données qui ne sont que dans l'entrepôt (base apisolscore, sur un autre serveur) :
l'identifiant des affaires (affaire.id, qui devient projects.id) et, pour les sondages, fiabilité,
types d'essais, niveaux d'eau et notation géologique. Une migration ne voit que la base métier : ces
données sont d'abord copiées ici par app/database/v3_staging.py, puis lues par les migrations
suivantes (0015 à 0017). 0020 supprime ces tables.

Ordre du basculement :
    alembic upgrade 0014
    python -m app.database.v3_staging
    alembic upgrade head
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Une ligne par affaire de l'entrepôt : son n° (notre projects.id actuel) et son identifiant.
    op.execute(
        """
        CREATE TABLE v3_warehouse_projects (
            project_number text PRIMARY KEY,
            warehouse_id text NOT NULL UNIQUE,
            business_unit_code text,
            geolocation_reliability integer
        )
        """
    )
    # Une ligne par sondage non supprimé : sondage.nom de l'entrepôt vaut notre surveys.id (« 77GT.19.0220_SP_2 »).
    op.execute(
        """
        CREATE TABLE v3_warehouse_surveys (
            project_number text NOT NULL,
            survey_id text NOT NULL,
            geolocation_reliability integer,
            has_pressuremeter boolean NOT NULL,
            has_penetrometer boolean NOT NULL,
            has_lithology boolean NOT NULL,
            has_water_levels boolean NOT NULL,
            geological_notation text,
            PRIMARY KEY (project_number, survey_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS v3_warehouse_surveys")
    op.execute("DROP TABLE IF EXISTS v3_warehouse_projects")
