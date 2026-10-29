"""Basculement v3, étape 4 : sondages, lithologies, pressions, essais pénétrométriques, niveaux d'eau.

surveys : name (l'id sans le préfixe du site ou de l'affaire : « 77GT.19.0220_SP_2 » → « SP_2 »),
fiabilité, types d'essais, niveaux d'eau et notation géologique repris de l'entrepôt
(v3_warehouse_surveys, 911 537 sondages sur 934 151 retrouvés le 29/10/2026 ; les autres, créés dans
la refonte ou renommés, restent sans ces données) ; latitude et longitude reprises de geometry (sinon de
la position saisie, en WGS 84) ; has_pz_equipment à non ; colonnes saisies et ville retirées.

lithologies : comment devient description_fr, description_en et classes lithologiques ajoutées, type retirée.
pressures : notations pressiométriques (em, pf, pl, p0).

penetrometer_tests, penetrometer_readings, water_levels_manual, water_levels_automatic : créées vides
(modèles de l'entrepôt ; leur reprise sera un chargement à part). geolocation_reliabilities : créée
vide, sens des niveaux à fournir par le métier.

Pas de retour arrière : restaurer le dump pris avant le basculement.
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Colonnes à valeur par défaut constante : ajoutées sans réécrire les 934 000 lignes (PostgreSQL 11+).
    op.execute(
        """
        ALTER TABLE surveys
            ADD COLUMN name text,
            ADD COLUMN fiab_geo_surveys integer,
            ADD COLUMN has_pressuremeter boolean NOT NULL DEFAULT false,
            ADD COLUMN has_penetrometer boolean NOT NULL DEFAULT false,
            ADD COLUMN has_lithology boolean NOT NULL DEFAULT false,
            ADD COLUMN has_water_levels boolean,
            ADD COLUMN geological_notation text,
            ADD COLUMN latitude float8,
            ADD COLUMN longitude float8,
            ADD COLUMN has_pz_equipment boolean NOT NULL DEFAULT false
        """
    )
    op.execute(
        """
        UPDATE surveys sv
        SET name = CASE
                WHEN starts_with(sv.id, s.id || '_') THEN substr(sv.id, length(s.id) + 2)
                WHEN starts_with(sv.id, p.project_number || '_') THEN substr(sv.id, length(p.project_number) + 2)
                ELSE sv.id
            END
        FROM sites s
        JOIN projects p ON p.id = s.project_id
        WHERE s.id = sv.site_id
        """
    )
    op.execute(
        """
        UPDATE surveys sv
        SET fiab_geo_surveys = w.geolocation_reliability,
            has_pressuremeter = w.has_pressuremeter,
            has_penetrometer = w.has_penetrometer,
            has_lithology = w.has_lithology,
            has_water_levels = w.has_water_levels,
            geological_notation = w.geological_notation
        FROM sites s
        JOIN projects p ON p.id = s.project_id
        JOIN v3_warehouse_surveys w ON w.project_number = p.project_number
        WHERE s.id = sv.site_id AND w.survey_id = sv.id
        """
    )
    op.execute("UPDATE surveys SET longitude = ST_X(geometry), latitude = ST_Y(geometry) WHERE geometry IS NOT NULL")
    op.execute(
        """
        UPDATE surveys
        SET longitude = longitude_saisie,
            latitude = latitude_saisie,
            geometry = ST_SetSRID(ST_MakePoint(longitude_saisie, latitude_saisie), 4326)
        WHERE geometry IS NULL
          AND longitude_saisie BETWEEN -180 AND 180
          AND latitude_saisie BETWEEN -90 AND 90
          AND coalesce(systeme_geo, 'WGS 1984') = 'WGS 1984'
        """
    )
    op.execute("ALTER TABLE surveys DROP COLUMN city, DROP COLUMN longitude_saisie, DROP COLUMN latitude_saisie, DROP COLUMN systeme_geo")
    op.execute("CREATE INDEX idx_surveys_test_types ON surveys (has_pressuremeter, has_penetrometer, has_lithology)")

    op.execute("ALTER TABLE lithologies RENAME COLUMN comment TO description_fr")
    op.execute(
        """
        ALTER TABLE lithologies
            ADD COLUMN description_en text,
            ADD COLUMN primary_lithology_category text,
            ADD COLUMN secondary_lithology_category text,
            DROP COLUMN type
        """
    )

    for old, new in (("pressiometric_test", "em"), ("creep_pressure", "pf"), ("limit_pressure", "pl"), ("h_gama", "p0")):
        op.execute(f"ALTER TABLE pressures RENAME COLUMN {old} TO {new}")

    op.execute(
        """
        CREATE TABLE penetrometer_tests (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            survey_id varchar(100) NOT NULL REFERENCES surveys (id) ON DELETE CASCADE,
            name text,
            type text,
            stop_criterion text,
            hammer_drop_height float8,
            tip_section float8,
            hammer_mass float8,
            anvil_mass float8,
            rod_mass float8,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz
        )
        """
    )
    op.execute("CREATE INDEX idx_penetrometer_tests_survey ON penetrometer_tests (survey_id)")
    op.execute(
        """
        CREATE TABLE penetrometer_readings (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            test_id uuid NOT NULL REFERENCES penetrometer_tests (id) ON DELETE CASCADE,
            depth float8 NOT NULL,
            blow_count float8,
            qd float8
        )
        """
    )
    op.execute("CREATE INDEX idx_penetrometer_readings_test_depth ON penetrometer_readings (test_id, depth)")

    op.execute(
        """
        CREATE TABLE water_levels_manual (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            survey_id varchar(100) NOT NULL REFERENCES surveys (id) ON DELETE CASCADE,
            measured_at timestamptz,
            depth_m float8,
            level_ref float8,
            referentiel text,
            kind text
        )
        """
    )
    op.execute("CREATE INDEX idx_water_levels_survey ON water_levels_manual (survey_id)")
    op.execute(
        """
        CREATE TABLE water_levels_automatic (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            survey_id varchar(100) NOT NULL REFERENCES surveys (id) ON DELETE CASCADE,
            measured_at timestamptz,
            depth_m float8,
            level_ref float8,
            referentiel text
        )
        """
    )
    op.execute("CREATE INDEX idx_water_levels_automatic_survey ON water_levels_automatic (survey_id, measured_at)")

    op.execute(
        """
        CREATE TABLE geolocation_reliabilities (
            scope text NOT NULL CHECK (scope IN ('project', 'site', 'survey')),
            level integer NOT NULL,
            reliability text NOT NULL CHECK (reliability IN ('reliable', 'unreliable', 'reported')),
            libelle text NOT NULL,
            PRIMARY KEY (scope, level)
        )
        """
    )


def downgrade() -> None:
    raise RuntimeError("Basculement v3 sans retour arrière : restaurer le dump pris avant la migration 0014.")
