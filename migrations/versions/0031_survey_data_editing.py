"""Édition des données d'un sondage (US-CARTE-41 à 45 du front), décisions du 06/11/2026 :

- pressures.em devient facultatif : la tâche accepte une ligne avec la profondeur et une seule autre mesure
  (1 149 essais avaient déjà Em = 0 faute de valeur) ;
- caractéristiques hydrodynamiques d'un sondage : une ligne par essai dans water_testing_parameters (mode
  prélèvement ou injection, pompage longue durée, lanterne en m/TA, perméabilité retenue obligatoire,
  transmissivité et coefficient d'emmagasinement facultatifs, faciès, notes), rangées par position ;
- surveys.is_water_testing : vrai quand le sondage a au moins un essai, pour filtrer les sondages
  (comme has_lithology, has_pressuremeter…). Nom de table et emplacement du pompage longue durée
  décidés avec l'équipe le 06/11/2026.

Retour arrière : les Em vides repassent à 0, comme avant, pour rétablir NOT NULL.
"""

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE pressures ALTER COLUMN em DROP NOT NULL")
    op.execute("ALTER TABLE surveys ADD COLUMN is_water_testing boolean NOT NULL DEFAULT false")
    op.execute(
        """
        CREATE TABLE water_testing_parameters (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            survey_id           varchar(100) NOT NULL REFERENCES surveys (id) ON DELETE CASCADE,
            position            integer NOT NULL,
            mode                text NOT NULL CHECK (mode IN ('withdrawal', 'injection')),
            long_duration_pumping boolean NOT NULL DEFAULT false,
            screen_top          float8,
            screen_base         float8 NOT NULL,
            permeability        float8 NOT NULL CHECK (permeability > 0),
            transmissivity      float8 CHECK (transmissivity > 0),
            storage_coefficient float8 CHECK (storage_coefficient > 0),
            facies              text,
            notes               text,
            CHECK (screen_top IS NULL OR screen_base > screen_top)
        )
        """
    )
    op.execute("CREATE INDEX idx_water_testing_parameters_survey ON water_testing_parameters (survey_id, position)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS water_testing_parameters")
    op.execute("ALTER TABLE surveys DROP COLUMN IF EXISTS is_water_testing")
    op.execute("UPDATE pressures SET em = 0 WHERE em IS NULL")
    op.execute("ALTER TABLE pressures ALTER COLUMN em SET NOT NULL")
