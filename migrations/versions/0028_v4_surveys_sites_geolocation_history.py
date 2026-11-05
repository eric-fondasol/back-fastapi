"""Commentaires du 04/11/2026 sur le schéma v4, tranchés par le responsable du projet le 05/11/2026.

- surveys : is_survey_fondasol (boolean, vrai par défaut : les sondages actuels viennent de l'entrepôt
  Fondasol), contractor (texte libre : prestataire qui a réalisé le sondage) et file_url (chemin du fichier
  du sondage, avant son passage dans la GED). Valeur par défaut constante : les 934 000 sondages ne sont
  pas réécrits (PostgreSQL 11+).
- sites : provided_external_data_id (uuid, facultatif) : identifiant de données externes fournies pour le
  site. Ni table quotes ni quote_id (décision du 05/11/2026).
- correction_sites devient geolocation_correction_history, comme dans le schéma v4 : une ligne par
  modification de géolocalisation d'un site ou d'un sondage, avec l'ANCIENNE position (la nouvelle est
  écrite dans sites ou surveys). id devient une clé primaire uuid ; site_id (obligatoire) et survey_id
  (vide quand c'est le site qui a été déplacé) sont ajoutés, avec suppression en cascade ; valid,
  a_envoyer et horodatage_correction, propres au circuit de validation de l'ancien front, sont retirées ;
  horodatage devient obligatoire, maintenant par défaut.

Lignes déjà présentes (la table est vide dans fondasol) : l'ancien id portait le n° du site (back
Symfony, import CSV id_site), il passe dans site_id et la ligne reçoit un uuid ; horodatage manquant pris
dans horodatage_correction, sinon maintenant. Un site inconnu fait échouer la migration (clé étrangère).

Retour arrière : l'ancien id reprend le n° du site ; survey_id, les champs de surveys et de sites sont
perdus ; valid, a_envoyer et horodatage_correction reviennent vides.
"""

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE surveys
            ADD COLUMN is_survey_fondasol boolean NOT NULL DEFAULT true,
            ADD COLUMN contractor text,
            ADD COLUMN file_url text
        """
    )
    op.execute("ALTER TABLE sites ADD COLUMN provided_external_data_id uuid")

    op.execute("ALTER TABLE correction_sites RENAME TO geolocation_correction_history")
    op.execute(
        """
        ALTER TABLE geolocation_correction_history
            ADD COLUMN site_id varchar(100),
            ADD COLUMN survey_id varchar(100)
        """
    )
    op.execute(
        """
        UPDATE geolocation_correction_history
        SET site_id = id, horodatage = coalesce(horodatage, horodatage_correction, now())
        """
    )
    op.execute(
        """
        ALTER TABLE geolocation_correction_history
            DROP COLUMN valid,
            DROP COLUMN a_envoyer,
            DROP COLUMN horodatage_correction,
            ALTER COLUMN id TYPE uuid USING gen_random_uuid(),
            ALTER COLUMN id SET DEFAULT gen_random_uuid(),
            ADD CONSTRAINT geolocation_correction_history_pkey PRIMARY KEY (id),
            ALTER COLUMN site_id SET NOT NULL,
            ADD CONSTRAINT geolocation_correction_history_site_fkey
                FOREIGN KEY (site_id) REFERENCES sites (id) ON DELETE CASCADE,
            ADD CONSTRAINT geolocation_correction_history_survey_fkey
                FOREIGN KEY (survey_id) REFERENCES surveys (id) ON DELETE CASCADE,
            ALTER COLUMN horodatage SET DEFAULT now(),
            ALTER COLUMN horodatage SET NOT NULL
        """
    )
    op.execute("CREATE INDEX idx_geolocation_correction_history_site ON geolocation_correction_history (site_id, horodatage DESC)")
    op.execute("CREATE INDEX idx_geolocation_correction_history_survey ON geolocation_correction_history (survey_id, horodatage DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_geolocation_correction_history_survey")
    op.execute("DROP INDEX IF EXISTS idx_geolocation_correction_history_site")
    op.execute(
        """
        ALTER TABLE geolocation_correction_history
            DROP CONSTRAINT geolocation_correction_history_survey_fkey,
            DROP CONSTRAINT geolocation_correction_history_site_fkey,
            DROP CONSTRAINT geolocation_correction_history_pkey,
            ALTER COLUMN id DROP DEFAULT,
            ALTER COLUMN id TYPE text USING site_id
        """
    )
    op.execute(
        """
        ALTER TABLE geolocation_correction_history
            ALTER COLUMN horodatage DROP NOT NULL,
            ALTER COLUMN horodatage DROP DEFAULT,
            DROP COLUMN survey_id,
            DROP COLUMN site_id,
            ADD COLUMN valid boolean,
            ADD COLUMN a_envoyer boolean,
            ADD COLUMN horodatage_correction timestamptz
        """
    )
    op.execute("ALTER TABLE geolocation_correction_history RENAME TO correction_sites")
    op.execute("ALTER TABLE sites DROP COLUMN provided_external_data_id")
    op.execute("ALTER TABLE surveys DROP COLUMN file_url, DROP COLUMN contractor, DROP COLUMN is_survey_fondasol")
