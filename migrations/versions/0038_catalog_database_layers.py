"""Couches du catalogue stockées en base (ADR-0062 du front) : objets et tuiles d'images rangés dans la base
métier au lieu d'être demandés à un service (demande du métier du 12/11/2026 pour le Canada).

Deux types de couches :
- « database » : objets (GeoJSON) de la table catalog_layer_features, servis par la route des objets
  (GET /layer-catalog/{code}/features), découpés à l'emprise et simplifiés au zoom par PostGIS ;
- « database-tiles » : tuiles d'images (grille XYZ Web Mercator) de la table catalog_layer_tiles, servies
  par la route des tuiles (GET /layer-catalog/{code}/tiles/{z}/{x}/{y}).
Ces couches n'ont pas d'adresse : url est NULL pour elles, et obligatoire pour les autres.
catalog_layer_legends garde l'image de légende d'une couche (GET /layer-catalog/{code}/legend).

La migration ne crée que les tables et les fiches des sept couches. Les données arrivent par
app/domains/layer_catalog/imports.py (procédure dans docs/couches/couches-en-base.md) : 75 Mo de géométries et
des milliers de tuiles n'ont pas leur place dans une migration. Tant qu'une couche n'est pas importée, elle
reste au catalogue mais n'affiche rien.

Les sept couches (Canada, île de Montréal pour les cinq dernières) :
- aires de protection des prélèvements d'eau potable, souterraine et de surface (shapefiles du MELCCFP déjà
  lus par l'API Solscore v2 pour l'enquête) : couleur selon Nom_AP, comme dans l'API v2 ;
- carte 1426 des dépôts meubles, en polygones (couleurs reprises des styles du KMZ, par code de dépôt) et en
  image (planche scannée, avec sa légende) ;
- carte 1427 de la profondeur du roc et carte hydrogéologique : images ;
- isopièzes de la carte hydrogéologique (Hypsometr.kmz) : lignes étiquetées par l'élévation de la nappe.

Toutes les instructions sont rejouables (IF NOT EXISTS, ON CONFLICT) : la base locale a reçu cette migration
par ses fonctions avant que la 0037 (rôles) n'arrive sur recette.

Retour arrière : les sept couches et les trois tables sont supprimées, url redevient obligatoire.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

STORED_KINDS = ("database", "database-tiles")

MELCCFP = "© Gouvernement du Québec – MELCCFP"
GSC = "© Ressources naturelles Canada – Commission géologique du Canada"
HYDROGEOLOGY = "© Gouvernement du Québec – carte hydrogéologique de l'île de Montréal"


def label(fr, en):
    return {"fr": fr, "en": en}


GROUNDWATER_CLASSES = {
    "property": "Nom_AP",
    "values": [
        {"value": "1", "color": "#e60000", "label": label("Immédiate", "Immediate")},
        {"value": "2", "color": "#ff6b00", "label": label("Intermédiaire bactériologique", "Intermediate, bacteriological")},
        {"value": "3", "color": "#ff00c5", "label": label("Intermédiaire virologique", "Intermediate, virological")},
        {"value": "4", "color": "#a900e6", "label": label("Éloignée", "Remote")},
    ],
}

SURFACE_WATER_CLASSES = {
    "property": "Nom_AP",
    "values": [
        {"value": "1", "color": "#e60000", "label": label("Immédiate", "Immediate")},
        {"value": "2", "color": "#ff6b00", "label": label("Intermédiaire", "Intermediate")},
    ],
}

# Couleur de remplissage de chaque code de dépôt dans le KMZ (styles PolyStyle de geo1426_ply_DépôtsMeubles).
DEPOSIT_COLORS = {
    "#00a884": ["1", "1-2-3", "1-3", "1?", "3", "3?"],
    "#ffffbe": ["2", "2a", "2b", "2b_c", "2c"],
    "#bee8ff": ["4"],
    "#00a9e6": ["5", "5-5a?", "5a"],
    "#ffd37f": ["6", "6?"],
    "#e69800": ["7", "7a"],
    "#0084a8": ["8", "8a"],
    "#d7fce8": ["8/7"],
    "#ca7af5": ["9", "9a", "9b"],
    "#ffbebe": ["R", "R?", "Rm"],
}

DEPOSIT_CLASSES = {
    "property": "CODE",
    "values": [{"value": code, "color": color} for color, codes in DEPOSIT_COLORS.items() for code in codes],
}

LAYERS = [
    {
        "code": "ca-qc-aires-protection-eau-souterraine",
        "category": "eau-souterraine",
        "label": ("Aires de protection des eaux souterraines", "Groundwater protection areas"),
        "description": (
            "Aires de protection et niveau de vulnérabilité des sites de prélèvement municipaux d'eau potable en eau "
            "souterraine de catégorie 1 (MELCCFP).",
            "Protection areas and vulnerability of category 1 municipal drinking water withdrawal sites in groundwater "
            "(MELCCFP).",
        ),
        "kind": "database",
        "params": {"classes": GROUNDWATER_CLASSES},
        "attribution": MELCCFP,
        "zooms": (10, 20),
    },
    {
        "code": "ca-qc-aires-protection-eau-surface",
        "category": "eau-surface",
        "label": ("Aires de protection des eaux de surface", "Surface water protection areas"),
        "description": (
            "Aires de protection des sites de prélèvement municipaux d'eau potable en eau de surface de catégorie 1 "
            "(MELCCFP).",
            "Protection areas of category 1 municipal drinking water withdrawal sites in surface water (MELCCFP).",
        ),
        "kind": "database",
        "params": {"classes": SURFACE_WATER_CLASSES},
        "attribution": MELCCFP,
        "zooms": (9, 20),
    },
    {
        "code": "ca-mtl-depots-meubles-1426-polygones",
        "category": "geologie",
        "label": ("Dépôts meubles de l'île de Montréal (1426, polygones)", "Surficial deposits of Montréal Island (1426, polygons)"),
        "description": (
            "Polygones des dépôts meubles de la carte 1426A, colorés par code de dépôt ; signification des codes dans "
            "la légende de la carte 1426 en image (Commission géologique du Canada).",
            "Surficial deposit polygons of map 1426A, coloured by deposit code; codes are explained in the legend of "
            "the 1426 image map (Geological Survey of Canada).",
        ),
        "kind": "database",
        "params": {"classes": DEPOSIT_CLASSES},
        "attribution": GSC,
        "zooms": (10, 20),
    },
    {
        "code": "ca-mtl-depots-meubles-1426",
        "category": "geologie",
        "label": ("Carte des dépôts meubles de l'île de Montréal (1426)", "Surficial geology map of Montréal Island (1426)"),
        "description": (
            "Carte 1426A des dépôts meubles de l'île de Montréal, planche scannée (Commission géologique du Canada).",
            "Map 1426A, surficial geology of Montréal Island, scanned sheet (Geological Survey of Canada).",
        ),
        "kind": "database-tiles",
        "params": {"format": "image/webp"},
        "attribution": GSC,
        "zooms": (9, 15),
    },
    {
        "code": "ca-mtl-profondeur-roc-1427",
        "category": "geologie",
        "label": ("Profondeur du roc de l'île de Montréal (1427)", "Drift thickness of Montréal Island (1427)"),
        "description": (
            "Carte 1427A de l'épaisseur des dépôts meubles (profondeur du roc), planche scannée ; la légende donne "
            "l'échelle de conversion (Commission géologique du Canada).",
            "Map 1427A, drift thickness (depth to bedrock), scanned sheet; the legend gives the conversion scale "
            "(Geological Survey of Canada).",
        ),
        "kind": "database-tiles",
        "params": {"format": "image/webp"},
        "attribution": GSC,
        "zooms": (9, 15),
    },
    {
        "code": "ca-mtl-carte-hydrogeologique",
        "category": "eau-souterraine",
        "label": ("Carte hydrogéologique de l'île de Montréal", "Hydrogeological map of Montréal Island"),
        "description": (
            "Carte hydrogéologique de l'île de Montréal et des îles Perrot et Bizard, planche scannée avec sa légende.",
            "Hydrogeological map of Montréal Island and Perrot and Bizard islands, scanned sheet with its legend.",
        ),
        "kind": "database-tiles",
        "params": {"format": "image/webp"},
        "attribution": HYDROGEOLOGY,
        "zooms": (9, 15),
    },
    {
        "code": "ca-mtl-isopiezes",
        "category": "eau-souterraine",
        "label": ("Isopièzes de l'île de Montréal", "Groundwater contours of Montréal Island"),
        "description": (
            "Courbes d'égale élévation de la nappe de la carte hydrogéologique de l'île de Montréal, en mètres et en "
            "pieds.",
            "Groundwater level contours from the hydrogeological map of Montréal Island, in metres and feet.",
        ),
        "kind": "database",
        "params": {"color": "#0000ff", "labelField": "Élévation de la nappe (m)"},
        "attribution": HYDROGEOLOGY,
        "zooms": (10, 20),
    },
]


def upgrade() -> None:
    connection = op.get_bind()
    create_tables(connection)
    seed(connection)


# Séparée de upgrade pour que les tests puissent la rejouer sur une base qui l'a déjà.
def create_tables(connection: sa.Connection) -> None:
    for statement in (
        "ALTER TABLE catalog_layers DROP CONSTRAINT IF EXISTS catalog_layers_kind_check",
        "ALTER TABLE catalog_layers ADD CONSTRAINT catalog_layers_kind_check "
        "CHECK (kind IN ('wms', 'wmts', 'xyz', 'vector', 'wfs', 'geojson', 'database', 'database-tiles'))",
        "ALTER TABLE catalog_layers ALTER COLUMN url DROP NOT NULL",
        "ALTER TABLE catalog_layers DROP CONSTRAINT IF EXISTS catalog_layers_url_check",
        """
        ALTER TABLE catalog_layers ADD CONSTRAINT catalog_layers_url_check CHECK (
            CASE WHEN kind IN ('database', 'database-tiles') THEN url IS NULL
                 ELSE coalesce(url LIKE 'https://%' OR (kind IN ('wfs', 'geojson') AND url LIKE 'http://%'), false)
            END
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS catalog_layer_features (
            id bigserial PRIMARY KEY,
            layer_id uuid NOT NULL REFERENCES catalog_layers (id) ON DELETE CASCADE,
            geometry geometry(Geometry, 4326) NOT NULL,
            properties jsonb NOT NULL DEFAULT '{}'::jsonb
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_catalog_layer_features_geometry ON catalog_layer_features USING gist (geometry)",
        "CREATE INDEX IF NOT EXISTS idx_catalog_layer_features_layer ON catalog_layer_features (layer_id)",
        """
        CREATE TABLE IF NOT EXISTS catalog_layer_tiles (
            layer_id uuid NOT NULL REFERENCES catalog_layers (id) ON DELETE CASCADE,
            z smallint NOT NULL CHECK (z BETWEEN 0 AND 22),
            x integer NOT NULL CHECK (x >= 0),
            y integer NOT NULL CHECK (y >= 0),
            content bytea NOT NULL,
            content_type text NOT NULL CHECK (content_type LIKE 'image/%'),
            PRIMARY KEY (layer_id, z, x, y)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS catalog_layer_legends (
            layer_id uuid PRIMARY KEY REFERENCES catalog_layers (id) ON DELETE CASCADE,
            content bytea NOT NULL,
            content_type text NOT NULL CHECK (content_type LIKE 'image/%'),
            updated_at timestamp(0) with time zone NOT NULL DEFAULT now()
        )
        """,
    ):
        connection.execute(sa.text(statement))


# Séparée de upgrade pour que les tests, qui vident les tables, puissent la rejouer.
def seed(connection: sa.Connection) -> None:
    for layer in LAYERS:
        (label_fr, label_en), (description_fr, description_en), (min_zoom, max_zoom) = (
            layer["label"],
            layer["description"],
            layer["zooms"],
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO catalog_layers
                    (code, category_id, country, label_fr, label_en, description_fr, description_en, kind, url, params,
                     attribution, min_zoom, max_zoom, position)
                SELECT :code, c.id, 'ca', :label_fr, :label_en, :description_fr, :description_en, :kind, NULL,
                       CAST(:params AS jsonb), :attribution, :min_zoom, :max_zoom,
                       (SELECT coalesce(max(l.position), 0) + 1 FROM catalog_layers l WHERE l.category_id = c.id)
                FROM layer_categories c WHERE c.code = :category
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {
                "code": layer["code"],
                "category": layer["category"],
                "label_fr": label_fr,
                "label_en": label_en,
                "description_fr": description_fr,
                "description_en": description_en,
                "kind": layer["kind"],
                "params": json.dumps(layer["params"], ensure_ascii=False),
                "attribution": layer["attribution"],
                "min_zoom": min_zoom,
                "max_zoom": max_zoom,
            },
        )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("DELETE FROM catalog_layers WHERE kind = ANY(:kinds)"), {"kinds": list(STORED_KINDS)})
    for statement in (
        "DROP TABLE IF EXISTS catalog_layer_legends",
        "DROP TABLE IF EXISTS catalog_layer_tiles",
        "DROP TABLE IF EXISTS catalog_layer_features",
        "ALTER TABLE catalog_layers DROP CONSTRAINT IF EXISTS catalog_layers_url_check",
        "ALTER TABLE catalog_layers ALTER COLUMN url SET NOT NULL",
        "ALTER TABLE catalog_layers ADD CONSTRAINT catalog_layers_url_check "
        "CHECK (url LIKE 'https://%' OR (kind IN ('wfs', 'geojson') AND url LIKE 'http://%'))",
        "ALTER TABLE catalog_layers DROP CONSTRAINT IF EXISTS catalog_layers_kind_check",
        "ALTER TABLE catalog_layers ADD CONSTRAINT catalog_layers_kind_check "
        "CHECK (kind IN ('wms', 'wmts', 'xyz', 'vector', 'wfs', 'geojson'))",
    ):
        connection.execute(sa.text(statement))
