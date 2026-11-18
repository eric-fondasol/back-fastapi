"""Sites BASOL (pollution des sols suspectée ou avérée appelant une action des pouvoirs publics) en base, à la place
des flux WMS de Géorisques (demande du responsable du projet du 18/11/2026, sur le modèle des sites CASIAS de la
migration 0048 ; ADR-0071 du front).

Les couches « Pollution suspectée ou avérée - information de l'administration » (points :
fr-georisques-pollution-instruction-points, emprises : fr-georisques-pollution-instruction-polygones) affichaient
les WMS SSP_INSTR_GE_POINT et SSP_INSTR_GE_POLYGONE de Géorisques. Leurs sites viennent désormais de l'extrait
BASOL.gpkg (11 625 points et 7 650 emprises au 17/11/2026), importé dans une table dédiée par
app/domains/layer_catalog/basol.py (procédure dans docs/couches/couches-en-base.md), et servis en tuiles
vectorielles (MVT) par la route des tuiles du catalogue.

Comme casias_sites : une seule table pour les deux couches du fichier, shape vaut point ou polygon, clé
(shape, code_metier). Le fichier répète un site sur plusieurs communes (606 points et 600 emprises en double, même
géométrie, seules la commune et l'adresse changent) : l'import garde la première ligne du fichier. Toutes les
colonnes du fichier sont gardées, en texte sous leur nom d'origine (SOURCE_COLUMNS) ; une chaîne vide devient NULL.
geometry est en EPSG:3857.

Les deux couches passent au type basol, sans adresse ni image de légende : rouge (#d7301f), pour les distinguer du
bleu de CASIAS (le style de Géorisques n'était pas lisible, service en maintenance), contour sombre pour les points
(symbol = point). Zoom minimal 12, inchangé : 11 000 points sur la France, quelques Ko par tuile.

Retour arrière : les couches redeviennent les WMS de Géorisques, la table est supprimée.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None

POINTS = "fr-georisques-pollution-instruction-points"
POLYGONS = "fr-georisques-pollution-instruction-polygones"

SOURCE_COLUMNS = (
    "gml_id", "id", "code_metier", "id_inventaire_instruction", "date_debut", "date_fin", "description",
    "nom_etablissement", "adresse", "code_postal", "code_insee", "nom_commune", "code_departement", "nom_departement",
    "code_region", "nom_region", "statut_instruction", "date_maj", "x_wgs84", "y_wgs84", "polygone_wgs84", "maille",
    "date_scraping", "url_fiche",
)

KINDS_BEFORE = ("wms", "wmts", "xyz", "vector", "wfs", "geojson", "database", "database-tiles", "bss", "casias", "wetlands", "potential-wetlands")
ADDRESSLESS_BEFORE = ("database", "database-tiles", "bss", "casias", "wetlands", "potential-wetlands")
KINDS = (*KINDS_BEFORE, "basol")
ADDRESSLESS = (*ADDRESSLESS_BEFORE, "basol")

COLOR = "#d7301f"
OUTLINE = "#3f3f3f"

PARAMS = {
    POINTS: {"color": COLOR, "outline": OUTLINE, "symbol": "point"},
    POLYGONS: {"color": COLOR},
}
MIN_ZOOM = 12

WMS_URL = "https://georisques.gouv.fr/services"
WMS_LAYERS = {POINTS: "SSP_INSTR_GE_POINT", POLYGONS: "SSP_INSTR_GE_POLYGONE"}


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
        CREATE TABLE basol_sites (
            shape text NOT NULL CHECK (shape IN ('point', 'polygon')),
            {", ".join(f'"{column}" text' for column in SOURCE_COLUMNS)},
            geometry geometry(Geometry, 3857) NOT NULL,
            PRIMARY KEY (shape, code_metier)
        )
        """,
        "CREATE INDEX basol_sites_geometry ON basol_sites USING gist (geometry)",
        *_constraints(KINDS, ADDRESSLESS),
    ):
        connection.execute(sa.text(statement))
    switch_to_database(connection)


# Séparée de upgrade pour que les tests, qui vident les tables, puissent la rejouer.
def switch_to_database(connection: sa.Connection) -> None:
    for code, params in PARAMS.items():
        connection.execute(
            sa.text(
                """
                UPDATE catalog_layers
                SET kind = 'basol', url = NULL, params = CAST(:params AS jsonb), legend_url = NULL, min_zoom = :min_zoom,
                    updated_at = now()
                WHERE code = :code
                """
            ),
            {"code": code, "params": json.dumps(params), "min_zoom": MIN_ZOOM},
        )


def downgrade() -> None:
    connection = op.get_bind()
    for code, layer in WMS_LAYERS.items():
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
                "code": code,
                "url": WMS_URL,
                "params": json.dumps({"format": "image/png", "layers": layer, "version": "1.3.0"}),
                "min_zoom": MIN_ZOOM,
                "legend_url": f"{WMS_URL}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetLegendGraphic&FORMAT=image/png&LAYER={layer}&SLD_VERSION=1.1.0",
            },
        )
    for statement in ("DROP TABLE basol_sites", *_constraints(KINDS_BEFORE, ADDRESSLESS_BEFORE)):
        connection.execute(sa.text(statement))
