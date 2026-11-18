"""Sites CASIAS (anciens sites industriels et activités de service) en base, à la place des flux WMS de Géorisques
(demande du responsable du projet du 18/11/2026, sur le modèle des ouvrages BSS de la migration 0047 ; ADR-0068 du
front).

Les couches « Sites CASIAS (points) » (fr-georisques-casias-points) et « Sites CASIAS (polygones) »
(fr-georisques-casias-polygones) affichaient les WMS SSP_ETS_GE_POINT et SSP_ETS_GE_POLYGON de Géorisques. Leurs
sites viennent désormais de l'extrait CASIAS.gpkg (253 733 points et 3 756 emprises au 17/11/2026), importé dans
une table dédiée par app/domains/layer_catalog/casias.py (procédure dans docs/couches/couches-en-base.md), et
servis en tuiles vectorielles (MVT) par la route des tuiles du catalogue.

Une seule table pour les deux couches du fichier : shape vaut point ou polygon, et la clé est (shape, code_metier),
3 009 sites ayant à la fois un point et une emprise. Toutes les colonnes du fichier sont gardées, en texte sous leur
nom d'origine (SOURCE_COLUMNS) ; une chaîne vide devient NULL. geometry est en EPSG:3857, comme bss_wells : les
tuiles se calculent sans reprojection.

Les deux couches passent au type casias, sans adresse ni image de légende : bleu de la légende de Géorisques
(#4884cc), contour sombre pour les points (symbol = point, légende dessinée en rond par le front). Le zoom minimal
des points passe de 12 à 13, comme la BSS : au zoom 12, une tuile pèse 600 à 700 Ko au centre de Paris ou de Lyon
(193 et 412 Ko au zoom 13), et le WMS de Géorisques n'affichait rien au-dessus du 1/25 000 (environ zoom 14). Les
emprises, quelques Ko par tuile, gardent le zoom 12.

Retour arrière : les couches redeviennent les WMS de Géorisques, la table est supprimée.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None

POINTS = "fr-georisques-casias-points"
POLYGONS = "fr-georisques-casias-polygones"

SOURCE_COLUMNS = (
    "gml_id", "code_metier", "nom_inventaire", "code_inventaire", "nom_etablissement", "code_siret", "adresse",
    "code_postal", "code_insee", "nom_commune", "code_departement", "nom_departement", "code_region", "nom_region",
    "etat_activite", "nature_localisation", "x_wgs84", "y_wgs84", "polygone_wgs84", "fiche_risque", "maille",
    "date_scraping",
)

KINDS_BEFORE = ("wms", "wmts", "xyz", "vector", "wfs", "geojson", "database", "database-tiles", "bss")
ADDRESSLESS_BEFORE = ("database", "database-tiles", "bss")
KINDS = (*KINDS_BEFORE, "casias")
ADDRESSLESS = (*ADDRESSLESS_BEFORE, "casias")

COLOR = "#4884cc"
OUTLINE = "#3f3f3f"

PARAMS = {
    POINTS: {"color": COLOR, "outline": OUTLINE, "symbol": "point"},
    POLYGONS: {"color": COLOR},
}
MIN_ZOOMS = {POINTS: 13, POLYGONS: 12}
MIN_ZOOM_BEFORE = 12

WMS_URL = "https://georisques.gouv.fr/services"
WMS_LAYERS = {POINTS: "SSP_ETS_GE_POINT", POLYGONS: "SSP_ETS_GE_POLYGON"}


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
        CREATE TABLE casias_sites (
            shape text NOT NULL CHECK (shape IN ('point', 'polygon')),
            {", ".join(f'"{column}" text' for column in SOURCE_COLUMNS)},
            geometry geometry(Geometry, 3857) NOT NULL,
            PRIMARY KEY (shape, code_metier)
        )
        """,
        "CREATE INDEX casias_sites_geometry ON casias_sites USING gist (geometry)",
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
                SET kind = 'casias', url = NULL, params = CAST(:params AS jsonb), legend_url = NULL, min_zoom = :min_zoom,
                    updated_at = now()
                WHERE code = :code
                """
            ),
            {"code": code, "params": json.dumps(params), "min_zoom": MIN_ZOOMS[code]},
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
                "min_zoom": MIN_ZOOM_BEFORE,
                "legend_url": f"{WMS_URL}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetLegendGraphic&FORMAT=image/png&LAYER={layer}&SLD_VERSION=1.1.0",
            },
        )
    for statement in ("DROP TABLE casias_sites", *_constraints(KINDS_BEFORE, ADDRESSLESS_BEFORE)):
        connection.execute(sa.text(statement))
