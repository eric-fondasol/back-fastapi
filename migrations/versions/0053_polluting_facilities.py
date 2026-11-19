"""Établissements pollueurs (registre des émissions polluantes, IREP) en base, à la place du flux WMS de Géorisques
(demande du responsable du projet du 18/11/2026, sur le modèle des secteurs SIS de la migration 0052 ; ADR-0073
du front).

La couche « Établissements pollueurs » (fr-georisques-etablissements-pollueurs) affichait le WMS
ETABLISSEMENTS_POLLUEURS de Géorisques. Ses établissements viennent désormais de l'extrait
ETABLISSEMENTS_POLLUEURS.gpkg (23 197 points au 18/11/2026, une seule table), importé dans une table dédiée par
app/domains/layer_catalog/polluting_facilities.py (procédure dans docs/couches/couches-en-base.md), et servis en
tuiles vectorielles (MVT) par la route des tuiles du catalogue.

Même forme que les tables de sites (casias_sites, basol_sites, sis_sites), pour partager l'import et la tuile :
shape (toujours point ici). Le fichier n'a pas de code_metier : la clé est (shape, identifiant), l'identifiant
IREP de l'établissement, unique dans le fichier. Toutes les colonnes du fichier sont gardées, en texte sous leur
nom d'origine (SOURCE_COLUMNS) ; une chaîne vide devient NULL. geometry est en EPSG:3857.

La couche passe au type polluting-facilities, sans adresse ni image de légende : orange (#e08214), contour sombre
(symbol = point), pour la distinguer de CASIAS (bleu), BASOL (rouge) et SIS (violet). Zoom minimal 9, inchangé :
au zoom 9, la tuile la plus chargée (661 établissements) pèse 117 Ko (mesures dans l'ADR-0073).

Retour arrière : la couche redevient le WMS de Géorisques, la table est supprimée.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None

CODE = "fr-georisques-etablissements-pollueurs"

SOURCE_COLUMNS = ("gml_id", "identifiant", "idetab", "nom", "codeape", "cp", "maille", "date_scraping", "url_fiche")

KINDS_BEFORE = (
    "wms", "wmts", "xyz", "vector", "wfs", "geojson", "database", "database-tiles", "bss", "casias", "wetlands",
    "potential-wetlands", "basol", "sis",
)
ADDRESSLESS_BEFORE = ("database", "database-tiles", "bss", "casias", "wetlands", "potential-wetlands", "basol", "sis")
KINDS = (*KINDS_BEFORE, "polluting-facilities")
ADDRESSLESS = (*ADDRESSLESS_BEFORE, "polluting-facilities")

PARAMS = {"color": "#e08214", "outline": "#3f3f3f", "symbol": "point"}
MIN_ZOOM = 9

WMS_URL = "https://georisques.gouv.fr/services"
WMS_LAYER = "ETABLISSEMENTS_POLLUEURS"


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
        CREATE TABLE polluting_facilities (
            shape text NOT NULL CHECK (shape IN ('point', 'polygon')),
            {", ".join(f'"{column}" text' for column in SOURCE_COLUMNS)},
            geometry geometry(Geometry, 3857) NOT NULL,
            PRIMARY KEY (shape, identifiant)
        )
        """,
        "CREATE INDEX polluting_facilities_geometry ON polluting_facilities USING gist (geometry)",
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
            SET kind = 'polluting-facilities', url = NULL, params = CAST(:params AS jsonb), legend_url = NULL,
                min_zoom = :min_zoom, updated_at = now()
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
    for statement in ("DROP TABLE polluting_facilities", *_constraints(KINDS_BEFORE, ADDRESSLESS_BEFORE)):
        connection.execute(sa.text(statement))
