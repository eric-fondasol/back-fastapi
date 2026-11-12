"""Objets des couches fichier en PostGIS, servis en tuiles vectorielles (ADR-0065 du front, choix du responsable du
projet du 12/11/2026).

Le GeoJSON d'un bloc de user_layers.geojson (ADR-0037 du front) plafonnait une couche à 5 Mo : la carte géologique
harmonisée du BRGM (département 13, 11 140 polygones) en fait 36. Les objets vont dans user_layer_features,
géométrie en Web Mercator (EPSG:3857, celui des tuiles) avec un index spatial ; la route des tuiles les découpe
avec ST_AsMVT.

user_layers reçoit ce que la liste des couches renvoie sans lire les objets : emprise en degrés (bounds), noms des
propriétés texte ou nombre (fields, pour l'étiquette de l'éditeur de style) et nombre d'objets. imported_at marque
la fin de l'envoi par lots : une couche sans imported_at n'est pas listée.

Les couches fichier existantes sont recopiées (géométries ramenées aux latitudes du Web Mercator), puis la colonne
geojson est retirée.

La contrainte user_layers_source n'exige plus de GeoJSON pour une couche fichier : seulement l'absence d'adresse.

Retour arrière : le GeoJSON est reconstitué à partir des objets (couches achevées seulement), puis la table et les
colonnes sont supprimées.
"""

import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

MERCATOR_LATITUDE = 85.0511


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            CREATE TABLE user_layer_features (
                id bigserial PRIMARY KEY,
                layer_id uuid NOT NULL REFERENCES user_layers (id) ON DELETE CASCADE,
                geometry geometry(Geometry, 3857) NOT NULL,
                properties jsonb NOT NULL DEFAULT '{}'
            )
            """
        )
    )
    connection.execute(sa.text("CREATE INDEX user_layer_features_layer_idx ON user_layer_features (layer_id)"))
    connection.execute(sa.text("CREATE INDEX user_layer_features_geometry_idx ON user_layer_features USING gist (geometry)"))
    connection.execute(
        sa.text(
            """
            ALTER TABLE user_layers
                ADD COLUMN bounds double precision[],
                ADD COLUMN fields jsonb NOT NULL DEFAULT '[]',
                ADD COLUMN feature_count integer NOT NULL DEFAULT 0,
                ADD COLUMN imported_at timestamp(0) with time zone
            """
        )
    )
    connection.execute(
        sa.text(
            f"""
            INSERT INTO user_layer_features (layer_id, geometry, properties)
            SELECT layer_id, ST_Transform(clipped, 3857), properties
            FROM (
                SELECT l.id AS layer_id,
                       ST_ClipByBox2D(
                           ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(feature -> 'geometry'), 4326)),
                           ST_MakeEnvelope(-180, -{MERCATOR_LATITUDE}, 180, {MERCATOR_LATITUDE}, 4326)
                       ) AS clipped,
                       COALESCE(NULLIF(feature -> 'properties', 'null'::jsonb), '{{}}'::jsonb) AS properties
                FROM user_layers l, jsonb_array_elements(l.geojson -> 'features') AS feature
                WHERE l.kind = 'file' AND l.geojson IS NOT NULL
            ) features
            WHERE NOT ST_IsEmpty(clipped)
            """
        )
    )
    connection.execute(sa.text("UPDATE user_layers SET imported_at = created_at WHERE kind = 'file'"))
    connection.execute(
        sa.text(
            """
            UPDATE user_layers l
            SET bounds = ARRAY[ST_XMin(summary.extent), ST_YMin(summary.extent), ST_XMax(summary.extent), ST_YMax(summary.extent)],
                feature_count = summary.count,
                fields = COALESCE((
                    SELECT jsonb_agg(DISTINCT entry.key ORDER BY entry.key)
                    FROM user_layer_features f, jsonb_each(f.properties) AS entry
                    WHERE f.layer_id = l.id AND jsonb_typeof(entry.value) IN ('string', 'number')
                ), '[]'::jsonb)
            FROM (
                SELECT layer_id, count(*)::integer AS count, ST_Extent(ST_Transform(geometry, 4326)) AS extent
                FROM user_layer_features GROUP BY layer_id
            ) summary
            WHERE l.id = summary.layer_id
            """
        )
    )
    connection.execute(sa.text("ALTER TABLE user_layers DROP CONSTRAINT user_layers_source"))
    connection.execute(sa.text("ALTER TABLE user_layers DROP COLUMN geojson"))
    connection.execute(
        sa.text(
            "ALTER TABLE user_layers ADD CONSTRAINT user_layers_source "
            "CHECK ((kind = 'file' AND url IS NULL) OR (kind <> 'file' AND url IS NOT NULL))"
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("ALTER TABLE user_layers ADD COLUMN geojson jsonb"))
    connection.execute(
        sa.text(
            """
            UPDATE user_layers l
            SET geojson = jsonb_build_object(
                'type', 'FeatureCollection',
                'features', (
                    SELECT COALESCE(jsonb_agg(jsonb_build_object(
                        'type', 'Feature',
                        'geometry', ST_AsGeoJSON(ST_Transform(f.geometry, 4326), 6)::jsonb,
                        'properties', f.properties
                    ) ORDER BY f.id), '[]'::jsonb)
                    FROM user_layer_features f WHERE f.layer_id = l.id
                )
            )
            WHERE l.kind = 'file' AND l.imported_at IS NOT NULL
            """
        )
    )
    connection.execute(sa.text("DELETE FROM user_layers WHERE kind = 'file' AND imported_at IS NULL"))
    connection.execute(sa.text("ALTER TABLE user_layers DROP CONSTRAINT user_layers_source"))
    connection.execute(
        sa.text(
            "ALTER TABLE user_layers ADD CONSTRAINT user_layers_source CHECK ("
            "(kind = 'file' AND geojson IS NOT NULL AND url IS NULL) OR (kind <> 'file' AND url IS NOT NULL AND geojson IS NULL))"
        )
    )
    connection.execute(sa.text("DROP TABLE user_layer_features"))
    connection.execute(
        sa.text("ALTER TABLE user_layers DROP COLUMN bounds, DROP COLUMN fields, DROP COLUMN feature_count, DROP COLUMN imported_at")
    )
