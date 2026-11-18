"""Milieux humides du sud du Québec en base (table quebec_wetlands), servis en tuiles vectorielles (ADR-0069 du
front), sur le modèle des sites CASIAS (0048).

Source : mh_2023.gpkg, transmis par le métier le 18/11/2026, table milieux_humides_sudqc_nov2023 : 328 863
multipolygones en EPSG:4326, « Cartographie détaillée des milieux humides des secteurs habités du sud du Québec »
(Canards Illimités Canada et MELCCFP, 2009-2023, version de novembre 2023). Il n'est pas versionné.

Comme pour CASIAS, toutes les colonnes du fichier sont gardées en texte, sous leur nom passé en minuscules
(SOURCE_COLUMNS) ; une chaîne vide devient NULL. La clé est globalid (unique dans le fichier, stable d'une version
à l'autre, contrairement à objectid). geometry est en EPSG:3857 : les tuiles se calculent sans reprojection.

Le style style_mh.sld transmis avec le fichier est repris dans la table quebec_wetland_classes (demande du
responsable du projet du 18/11/2026 : une table liée à celle des milieux humides plutôt qu'un JSON dans params) :
une ligne par classe, code, couleur, libellé français (du style et du domaine MH_DOM_CLASSE du GeoPackage) et
anglais (colonne CLASS_NAME), ordre de la légende. quebec_wetlands.classe y renvoie par une clé étrangère : un
milieu d'une classe inconnue ne peut pas entrer en base. Le catalogue (services.catalog) en tire params.classes
pour le front.

La couche est nouvelle au catalogue (aucun WMS à remplacer) : « Eau de surface », Canada, type wetlands, sans
adresse ni image de légende. params.color est la couleur de la règle par défaut du style, pour un milieu sans
classe. params.fillOpacity porte le remplissage à 50 % (20 % pour les autres couches d'objets du front) : à 20 %,
les marécages (#55ff00) se confondaient avec le vert des parcs du fond de carte (retour du responsable du projet,
18/11/2026).

Retour arrière : la couche est retirée, les deux tables supprimées.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None

CODE = "ca-qc-milieux-humides"

SOURCE_COLUMNS = (
    "globalid", "objectid_1", "objectid", "classe", "class_name", "conf_delim", "conf_class", "typ_valid",
    "source_docum", "annee_docum", "source_photo", "annee_photo", "notes", "projet", "phases", "collaborateurs",
    "mh_ha", "pression_1", "pression_2", "pression_3", "pr_impact", "pr_note", "recno", "nm_createur",
    "da_creation", "nm_editeur", "da_modif", "da_geo", "shape_length", "shape_area",
)

KINDS_BEFORE = ("wms", "wmts", "xyz", "vector", "wfs", "geojson", "database", "database-tiles", "bss", "casias")
ADDRESSLESS_BEFORE = ("database", "database-tiles", "bss", "casias")
KINDS = (*KINDS_BEFORE, "wetlands")
ADDRESSLESS = (*ADDRESSLESS_BEFORE, "wetlands")


CLASSES = (
    ("BG", "#cdaa66", "Tourbière ouverte bog (ombrotrophe)", "Open bog peatland (ombrotrophic)"),
    ("FN", "#cdcd66", "Tourbière ouverte fen (minérotrophe)", "Open fen peatland (minerotrophic)"),
    ("TB", "#70a800", "Tourbière boisée", "Forested peatland"),
    ("ME", "#55ff00", "Marécage", "Swamp"),
    ("MS", "#ffbebe", "Marais", "Marsh"),
    ("PH", "#ffaa00", "Prairie humide", "Wet meadow"),
    ("EP", "#bee8ff", "Eau peu profonde", "Shallow water"),
)

PARAMS = {"color": "#97c919", "fillOpacity": 0.5}

WETLANDS = {
    "code": CODE,
    "category": "eau-surface",
    "label_fr": "Milieux humides (cartographie détaillée, sud du Québec)",
    "label_en": "Wetlands (detailed mapping, southern Quebec)",
    "description_fr": (
        "Cartographie détaillée des milieux humides des secteurs habités du sud du Québec (2009-2023, version de "
        "novembre 2023) : tourbières, marécages, marais, prairies humides et eau peu profonde."
    ),
    "description_en": (
        "Detailed mapping of wetlands in the inhabited areas of southern Quebec (2009-2023, November 2023 "
        "release): peatlands, swamps, marshes, wet meadows and shallow water."
    ),
    "attribution": "© Canards Illimités Canada et MELCCFP (2023)",
    "min_zoom": 12,
    "max_zoom": 19,
}


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
        """
        CREATE TABLE quebec_wetland_classes (
            code text PRIMARY KEY,
            color text NOT NULL CHECK (color ~ '^#[0-9a-f]{6}$'),
            label_fr text NOT NULL,
            label_en text,
            position integer NOT NULL UNIQUE
        )
        """,
        f"""
        CREATE TABLE quebec_wetlands (
            {", ".join(f'"{column}" text' for column in SOURCE_COLUMNS)},
            geometry geometry(Geometry, 3857) NOT NULL,
            PRIMARY KEY (globalid),
            FOREIGN KEY (classe) REFERENCES quebec_wetland_classes (code) ON UPDATE CASCADE ON DELETE RESTRICT
        )
        """,
        "CREATE INDEX quebec_wetlands_geometry ON quebec_wetlands USING gist (geometry)",
        *_constraints(KINDS, ADDRESSLESS),
    ):
        connection.execute(sa.text(statement))
    seed(connection)


# Séparée de upgrade pour que les tests, qui vident les tables, puissent la rejouer.
def seed(connection: sa.Connection) -> None:
    for position, (code, color, label_fr, label_en) in enumerate(CLASSES, start=1):
        connection.execute(
            sa.text(
                """
                INSERT INTO quebec_wetland_classes (code, color, label_fr, label_en, position)
                VALUES (:code, :color, :label_fr, :label_en, :position)
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {"code": code, "color": color, "label_fr": label_fr, "label_en": label_en, "position": position},
        )
    connection.execute(
        sa.text(
            """
            INSERT INTO catalog_layers
                (code, category_id, country, label_fr, label_en, description_fr, description_en, kind, url, params,
                 attribution, legend_url, min_zoom, max_zoom, position)
            SELECT :code, c.id, 'ca', :label_fr, :label_en, :description_fr, :description_en, 'wetlands', NULL,
                   CAST(:params AS jsonb), :attribution, NULL, :min_zoom, :max_zoom,
                   (SELECT coalesce(max(l.position), 0) + 1 FROM catalog_layers l WHERE l.category_id = c.id)
            FROM layer_categories c WHERE c.code = :category
            ON CONFLICT (code) DO NOTHING
            """
        ),
        {**WETLANDS, "params": json.dumps(PARAMS)},
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("DELETE FROM catalog_layers WHERE code = :code"), {"code": CODE})
    for statement in ("DROP TABLE quebec_wetlands", "DROP TABLE quebec_wetland_classes", *_constraints(KINDS_BEFORE, ADDRESSLESS_BEFORE)):
        connection.execute(sa.text(statement))
