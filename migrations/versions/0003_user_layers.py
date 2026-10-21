"""Couches ajoutées par l'utilisateur : flux (WMS, WMTS, XYZ) et, au lot 2, fichiers (ADR-0035 du front).

Un flux garde son adresse (url) et ses paramètres (params) ; un fichier, le chemin relatif de son
GeoJSON converti (file_path). La contrainte interdit d'avoir les deux, ou aucun.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_layers (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            name text NOT NULL,
            kind text NOT NULL CHECK (kind IN ('wms', 'wmts', 'xyz', 'file')),
            url text,
            params jsonb NOT NULL DEFAULT '{}'::jsonb,
            file_path text,
            original_name text,
            west double precision,
            south double precision,
            east double precision,
            north double precision,
            created_at timestamp(0) with time zone NOT NULL,
            updated_at timestamp(0) with time zone NOT NULL,
            CONSTRAINT user_layers_source CHECK (
                (kind = 'file' AND file_path IS NOT NULL AND url IS NULL)
                OR (kind <> 'file' AND url IS NOT NULL AND file_path IS NULL)
            )
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_layers_user ON user_layers (user_id, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_layers")
