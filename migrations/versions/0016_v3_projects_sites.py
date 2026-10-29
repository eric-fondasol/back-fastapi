"""Basculement v3, étape 3 : affaires, métiers, historique GED et sites.

projects : name devient project_description ; business_unit_code (centre analytique, code_service de
l'entrepôt s'il existe dans business_units) et fiab_geo_project (affaire.localisation_fiabilite)
ajoutées ; colonnes retirées par la réunion du 22/10/2026 : position (passe dans sites), doublons de
l'id, code_metier (passe dans project_business_lines), traces GED (passent dans docs_ged_changes).

project_business_lines : une ligne par affaire et métier, reprise de code_metier (« N/A » et vide écartés).
docs_ged_changes : reprise des deux modifications manuelles connues (auteur et date ; valeur d'avant inconnue).
no_docs_ged_reasons : créée vide, liste à fournir par le métier.

sites : fiability devient fiab_geo_sites ; latitude et longitude reprises de geometry (sinon de la
position saisie de l'affaire, si elle est en WGS 84), altitude de l'affaire ; geoloc_project_status créée
vide (le back le calcule aujourd'hui) ; updated_at retirée.

Pas de retour arrière : restaurer le dump pris avant le basculement.
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

GEOLOCATION_STATUSES = "('geolocated', 'to_geolocate', 'surveys_to_geolocate', 'impossible')"

RETIRED_PROJECT_COLUMNS = (
    "city_agency",
    "code_metier",
    "uuid",
    "externe_id",
    "altitude",
    "geometry",
    "user_email",
    "longitude_saisie",
    "latitude_saisie",
    "systeme_geo",
    "url_id",
    "is_doc_ged_updated_by",
    "is_doc_ged_updated_at",
)


def upgrade() -> None:
    op.execute("ALTER TABLE projects RENAME COLUMN name TO project_description")
    op.execute(
        """
        ALTER TABLE projects
            ADD COLUMN business_unit_code text REFERENCES business_units (code) ON DELETE SET NULL,
            ADD COLUMN fiab_geo_project integer
        """
    )
    op.execute(
        """
        UPDATE projects p
        SET business_unit_code = units.code, fiab_geo_project = w.geolocation_reliability
        FROM v3_warehouse_projects w
        LEFT JOIN business_units units ON units.code = w.business_unit_code
        WHERE w.project_number = p.project_number
        """
    )

    op.execute(
        """
        CREATE TABLE project_business_lines (
            project_id varchar(100) NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            business_line_code text NOT NULL REFERENCES business_lines (code) ON DELETE RESTRICT,
            PRIMARY KEY (project_id, business_line_code)
        )
        """
    )
    op.execute("CREATE INDEX idx_project_business_lines_line ON project_business_lines (business_line_code)")
    op.execute(
        """
        INSERT INTO project_business_lines (project_id, business_line_code)
        SELECT p.id, lines.code
        FROM projects p
        JOIN business_lines lines ON lines.code = trim(p.code_metier)
        """
    )

    op.execute("CREATE TABLE no_docs_ged_reasons (id integer PRIMARY KEY, libelle text NOT NULL)")
    op.execute(
        """
        CREATE TABLE docs_ged_changes (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id varchar(100) NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            is_doc_ged_old_value boolean,
            is_doc_ged_new_value boolean NOT NULL,
            no_docs_ged_reason_id integer REFERENCES no_docs_ged_reasons (id),
            user_email text NOT NULL,
            changed_at timestamptz NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX idx_docs_ged_changes_project ON docs_ged_changes (project_id, changed_at)")
    op.execute(
        """
        INSERT INTO docs_ged_changes (project_id, is_doc_ged_new_value, user_email, changed_at)
        SELECT id, is_doc_ged, is_doc_ged_updated_by, coalesce(is_doc_ged_updated_at, now())
        FROM projects
        WHERE is_doc_ged_updated_by IS NOT NULL
        """
    )

    op.execute("ALTER TABLE sites RENAME COLUMN fiability TO fiab_geo_sites")
    op.execute(
        f"""
        ALTER TABLE sites
            ADD COLUMN latitude float8,
            ADD COLUMN longitude float8,
            ADD COLUMN altitude float8,
            ADD COLUMN geoloc_project_status text CHECK (geoloc_project_status IN {GEOLOCATION_STATUSES})
        """
    )
    op.execute("UPDATE sites SET longitude = ST_X(geometry), latitude = ST_Y(geometry) WHERE geometry IS NOT NULL")
    # Position saisie de l'affaire, pour un site sans position : seulement en WGS 84 (ou sans système, WGS 84 par défaut).
    op.execute(
        """
        UPDATE sites s
        SET longitude = p.longitude_saisie,
            latitude = p.latitude_saisie,
            geometry = ST_SetSRID(ST_MakePoint(p.longitude_saisie, p.latitude_saisie), 4326)
        FROM projects p
        WHERE s.project_id = p.id
          AND s.geometry IS NULL
          AND p.longitude_saisie BETWEEN -180 AND 180
          AND p.latitude_saisie BETWEEN -90 AND 90
          AND coalesce(p.systeme_geo, 'WGS 1984') = 'WGS 1984'
        """
    )
    op.execute("UPDATE sites s SET altitude = p.altitude FROM projects p WHERE s.project_id = p.id AND p.altitude IS NOT NULL")
    op.execute("ALTER TABLE sites DROP COLUMN updated_at")

    op.execute(f"ALTER TABLE projects {', '.join(f'DROP COLUMN {column}' for column in RETIRED_PROJECT_COLUMNS)}")


def downgrade() -> None:
    raise RuntimeError("Basculement v3 sans retour arrière : restaurer le dump pris avant la migration 0014.")
