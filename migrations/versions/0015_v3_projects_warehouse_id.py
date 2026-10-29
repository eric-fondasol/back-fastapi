"""Basculement v3, étape 2 : projects.id devient l'identifiant de l'entrepôt (décision du 22/10/2026).

Le n° d'affaire (« 06GT.19.0012 »), jusqu'ici dans id, passe dans project_number, qui reprend l'index
de recherche tolérante (migration 0002). Le nouvel id est affaire.id de l'entrepôt (uuid, en texte),
lu dans v3_warehouse_projects (remplie par app/database/v3_staging.py). Le 29/10/2026, 303 465 affaires
sur 303 485 y ont un id ; les 20 autres reçoivent un uuid neuf (choix à confirmer, ADR-0048).

Les tables qui pointent vers projects.id sont reprises avec le nouvel id : sites, correction_sites,
user_favorite_projects. La correspondance ancien id → nouvel id reste dans v3_project_ids jusqu'à 0020.
saved_pages.project_ref garde le n° d'affaire (c'est un n°, pas un id).

Pas de retour arrière : restaurer le dump pris avant le basculement.
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

COMPACT_NUMBER = "regexp_replace(upper((project_number)::text), '[^A-Z0-9]'::text, ''::text, 'g'::text) text_pattern_ops"


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM projects) AND NOT EXISTS (SELECT 1 FROM v3_warehouse_projects) THEN
                RAISE EXCEPTION 'v3_warehouse_projects est vide : lancer python -m app.database.v3_staging avant cette migration';
            END IF;
        END
        $$
        """
    )

    op.execute("ALTER TABLE projects ADD COLUMN project_number varchar(100)")
    op.execute("UPDATE projects SET project_number = id")

    op.execute(
        """
        CREATE TABLE v3_project_ids (
            old_id varchar(100) PRIMARY KEY,
            new_id varchar(100) NOT NULL UNIQUE
        )
        """
    )
    op.execute(
        """
        INSERT INTO v3_project_ids (old_id, new_id)
        SELECT p.id, coalesce(w.warehouse_id, gen_random_uuid()::text)
        FROM projects p
        LEFT JOIN v3_warehouse_projects w ON w.project_number = p.id
        """
    )

    op.execute("ALTER TABLE user_favorite_projects DROP CONSTRAINT user_favorite_projects_project_fkey")
    for table in ("sites", "correction_sites", "user_favorite_projects"):
        op.execute(f"UPDATE {table} t SET project_id = m.new_id FROM v3_project_ids m WHERE t.project_id = m.old_id")
    op.execute("UPDATE projects p SET id = m.new_id FROM v3_project_ids m WHERE p.id = m.old_id")
    op.execute(
        """
        ALTER TABLE user_favorite_projects ADD CONSTRAINT user_favorite_projects_project_fkey
            FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
        """
    )

    op.execute("ALTER TABLE projects ALTER COLUMN project_number SET NOT NULL")
    op.execute("ALTER TABLE projects ADD CONSTRAINT projects_project_number_key UNIQUE (project_number)")
    op.execute("DROP INDEX IF EXISTS idx_projects_compact_id")
    op.execute(f"CREATE INDEX idx_projects_compact_id ON projects USING btree ({COMPACT_NUMBER})")


def downgrade() -> None:
    raise RuntimeError("Basculement v3 sans retour arrière : restaurer le dump pris avant la migration 0014.")
