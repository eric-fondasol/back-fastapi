"""Secteurs d'information sur les sols (SIS) en base, à la place du flux WMS de Géorisques (demande du responsable
du projet du 18/11/2026, sur le modèle des sites BASOL de la migration 0051 ; ADR-0072 du front).

La couche « Secteurs d'information sur les sols (SIS) » (fr-georisques-sis) affichait le WMS SSP_CLASSIF_SIS_GE de
Géorisques. Ses secteurs viennent désormais de l'extrait SIS.gpkg (6 006 emprises au 17/11/2026, une seule table,
sans points), importé dans une table dédiée par app/domains/layer_catalog/sis.py (procédure dans
docs/couches/couches-en-base.md), et servis en tuiles vectorielles (MVT) par la route des tuiles du catalogue.

Même forme que basol_sites, pour partager l'import, la tuile et la recherche dans un rayon : shape (toujours
polygon ici), clé (shape, code_metier). Le fichier répète un secteur sur plusieurs communes (310 lignes, même
géométrie) : l'import garde la première ligne du fichier. Toutes les colonnes du fichier sont gardées, en texte
sous leur nom d'origine (SOURCE_COLUMNS) ; une chaîne vide devient NULL. geometry est en EPSG:3857.

La couche passe au type sis, sans adresse ni image de légende : violet (#7b3294), pour la distinguer du bleu de
CASIAS et du rouge de BASOL. Zoom minimal 12, inchangé.

Retour arrière : la couche redevient le WMS de Géorisques, la table est supprimée.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None

CODE = "fr-georisques-sis"

SOURCE_COLUMNS = (
    "gml_id", "id_classification", "id_instruction", "code_metier", "id_inventaire_classification",
    "nom_etablissement", "date_ap", "adresse", "code_postal", "code_insee", "nom_commune", "code_departement",
    "code_region", "date_saisie_commune", "x_wgs84", "y_wgs84", "maille", "date_scraping", "url_fiche",
)

KINDS_BEFORE = (
    "wms", "wmts", "xyz", "vector", "wfs", "geojson", "database", "database-tiles", "bss", "casias", "wetlands",
    "potential-wetlands", "basol",
)
ADDRESSLESS_BEFORE = ("database", "database-tiles", "bss", "casias", "wetlands", "potential-wetlands", "basol")
KINDS = (*KINDS_BEFORE, "sis")
ADDRESSLESS = (*ADDRESSLESS_BEFORE, "sis")

PARAMS = {"color": "#7b3294"}
MIN_ZOOM = 12

WMS_URL = "https://georisques.gouv.fr/services"
WMS_LAYER = "SSP_CLASSIF_SIS_GE"


def _quoted(values):
    return ", ".join(f"'{value}'" for value in values)


def _constraints(kinds, addressless):
    return (
        "ALTER TABLE catalog_layers DROP CONSTRAINT IF EXISTS catalog_layers_kind_check",
        f"ALTER TABLE catalog_layers ADD CONSTRAINT catalog_layers_kind_check CHECK (kind IN ({_quoted(kinds)}))",
        "ALTER TABLE catalog_layers DROP CONSTRAINT IF EXISTS catalog_layers_url_check",
        f"""
        ALTER TABLE catalog_layers ADD CONSTRAINT catalog_layers_url_check CHECK (
            CASE WHEN kind IN ({_quoted(addressless)}) THEN url IS NULL
                 ELSE coalesce(url LIKE 'https://%' OR (kind IN ('wfs', 'geojson') AND url LIKE 'http://%'), false)
            END
        )
        """,
    )


def upgrade() -> None:
    connection = op.get_bind()
    for statement in (
        f"""
        CREATE TABLE sis_sites (
            shape text NOT NULL CHECK (shape IN ('point', 'polygon')),
            {", ".join(f'"{column}" text' for column in SOURCE_COLUMNS)},
            geometry geometry(Geometry, 3857) NOT NULL,
            PRIMARY KEY (shape, code_metier)
        )
        """,
        "CREATE INDEX sis_sites_geometry ON sis_sites USING gist (geometry)",
        *_constraints(KINDS, ADDRESSLESS),
    ):
        connection.execute(sa.text(statement))
    switch_to_database(connection)


# Séparée de upgrade pour que les tests, qui vident les tables, puissent la rejouer.
def switch_to_database(connection: sa.Connection) -> None:
    connection.execute(
        sa.text(
            """
            UPDATE catalog_layers
            SET kind = 'sis', url = NULL, params = CAST(:params AS jsonb), legend_url = NULL, min_zoom = :min_zoom,
                updated_at = now()
            WHERE code = :code
            """
        ),
        {"code": CODE, "params": json.dumps(PARAMS), "min_zoom": MIN_ZOOM},
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE catalog_layers
            SET kind = 'wms', url = :url, params = CAST(:params AS jsonb), legend_url = :legend_url, min_zoom = :min_zoom,
                updated_at = now()
            WHERE code = :code
            """
        ),
        {
            "code": CODE,
            "url": WMS_URL,
            "params": json.dumps({"format": "image/png", "layers": WMS_LAYER, "version": "1.3.0"}),
            "min_zoom": MIN_ZOOM,
            "legend_url": f"{WMS_URL}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetLegendGraphic&FORMAT=image/png&LAYER={WMS_LAYER}&SLD_VERSION=1.1.0",
        },
    )
    for statement in ("DROP TABLE sis_sites", *_constraints(KINDS_BEFORE, ADDRESSLESS_BEFORE)):
        connection.execute(sa.text(statement))
