"""Couches fichier : le GeoJSON converti est rangé en base (jsonb), plus sur disque (ADR-0037 du front).

Le navigateur lit le fichier déposé (GeoJSON, KML, KMZ, Shapefile) et envoie le GeoJSON WGS 84 ;
file_path, prévu par la révision 0003 et jamais utilisé, disparaît au profit de geojson.
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_layers ADD COLUMN IF NOT EXISTS geojson jsonb")
    op.execute("ALTER TABLE user_layers DROP CONSTRAINT IF EXISTS user_layers_source")
    op.execute("ALTER TABLE user_layers DROP COLUMN IF EXISTS file_path")
    op.execute(
        """
        ALTER TABLE user_layers ADD CONSTRAINT user_layers_source CHECK (
            (kind = 'file' AND geojson IS NOT NULL AND url IS NULL)
            OR (kind <> 'file' AND url IS NOT NULL AND geojson IS NULL)
        )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM user_layers WHERE kind = 'file'")
    op.execute("ALTER TABLE user_layers DROP CONSTRAINT IF EXISTS user_layers_source")
    op.execute("ALTER TABLE user_layers ADD COLUMN IF NOT EXISTS file_path text")
    op.execute("ALTER TABLE user_layers DROP COLUMN IF EXISTS geojson")
    op.execute(
        """
        ALTER TABLE user_layers ADD CONSTRAINT user_layers_source CHECK (
            (kind = 'file' AND file_path IS NOT NULL AND url IS NULL)
            OR (kind <> 'file' AND url IS NOT NULL AND file_path IS NULL)
        )
        """
    )
