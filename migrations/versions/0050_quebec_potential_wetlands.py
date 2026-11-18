"""Milieux humides potentiels du Québec en base (table quebec_potential_wetlands), servis en tuiles vectorielles
(ADR-0070 du front), sur le modèle des milieux humides de la cartographie détaillée (0049).

Source : mh_potentiel_2023.gpkg, transmis par le métier le 18/11/2026, table mh_potentiel_qc : 2 446 410
multipolygones en NAD83 / Québec Lambert (EPSG:32198), sur tout le Québec ; « Milieux humides potentiels 2019 »
(MELCC - DCE, d'après les métadonnées du fichier). Il n'est pas versionné. Ses sources (colonne SOURCE)
comprennent la cartographie détaillée de 2019 (MH_DETAIL, 294 546 polygones), qui recouvre en partie la couche
ca-qc-milieux-humides (version de 2023) : tout est importé (demande du responsable du projet du 18/11/2026), les
deux couches restent distinctes.

Toutes les colonnes du fichier sont gardées en texte, sous leur nom en minuscules ; clé objectid (unique dans le
fichier) ; geometry en EPSG:3857.

Style (style.sld et style QGIS du fichier, table layer_styles) dans quebec_potential_wetland_classes, liée par une
clé étrangère sur la classe, comme quebec_wetland_classes : le fichier n'a pas de code, la clé est la valeur de
CLASSE, en clair. Chaque classe a un remplissage et un contour (outline, à garder d'après le responsable du
projet). « Eau peu profonde » et « Marais » ont dans QGIS un remplissage en texture (fond pointillé), que le SLD
n'exporte pas et que le front ne dessine pas : aplat de la couleur moyenne de la texture (#aebcff, #ffb3ab).
quebec_wetland_classes reçoit aussi une colonne outline, vide (le style de mh_2023 n'a pas de contour), pour que
les deux tables de style aient la même forme.

La couche est nouvelle au catalogue : « Eau de surface », Canada, type potential-wetlands, sans adresse ni image
de légende ; params.color pour un milieu sans classe, params.fillOpacity à 0,5 comme la cartographie détaillée.

Retour arrière : la couche est retirée, les deux tables supprimées, la colonne outline retirée.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None

CODE = "ca-qc-milieux-humides-potentiels"

SOURCE_COLUMNS = (
    "objectid", "source", "confiance", "superficie", "classe", "type", "physionomie", "sys_trophique",
    "particularite", "shape_length", "shape_area",
)

KINDS_BEFORE = ("wms", "wmts", "xyz", "vector", "wfs", "geojson", "database", "database-tiles", "bss", "casias", "wetlands")
ADDRESSLESS_BEFORE = ("database", "database-tiles", "bss", "casias", "wetlands")
KINDS = (*KINDS_BEFORE, "potential-wetlands")
ADDRESSLESS = (*ADDRESSLESS_BEFORE, "potential-wetlands")

CLASSES = (
    ("Eau peu profonde", "#aebcff", "#6677cd", "Eau peu profonde", "Shallow water"),
    ("Prairie humide", "#f5f57a", "#ffd37f", "Prairie humide", "Wet meadow"),
    ("Marais", "#ffb3ab", "#ff8f7f", "Marais", "Marsh"),
    ("Marécage", "#a3ff73", "#70a800", "Marécage indifférencié", "Undifferentiated swamp"),
    ("Tourbière boisée", "#5c8944", "#4c7300", "Tourbière boisée", "Forested peatland"),
    ("Tourbière ouverte indifférenciée", "#ffebaf", "#e69800", "Tourbière ouverte indifférenciée", "Undifferentiated open peatland"),
    ("Tourbière ouverte minérotrophe", "#f5ca7a", "#a87000", "Tourbière ouverte minérotrophe", "Open minerotrophic peatland (fen)"),
    ("Tourbière ouverte ombrotrophe", "#cdaa66", "#8c671c", "Tourbière ouverte ombrotrophe", "Open ombrotrophic peatland (bog)"),
    ("Complexe palsique", "#df7fc2", "#6e6e6e", "Complexe palsique", "Palsa complex"),
    ("Milieu humide indifférencié", "#cccccc", "#686868", "Milieu humide indifférencié", "Undifferentiated wetland"),
)

PARAMS = {"color": "#cccccc", "fillOpacity": 0.5}

POTENTIAL_WETLANDS = {
    "code": CODE,
    "category": "eau-surface",
    "label_fr": "Milieux humides potentiels (Québec)",
    "label_en": "Potential wetlands (Quebec)",
    "description_fr": (
        "Milieux humides potentiels de tout le Québec (MELCC, 2019), assemblés à partir de plusieurs inventaires. "
        "Localisation potentielle, sans valeur légale : ne remplace pas un inventaire détaillé sur le terrain et ne "
        "sert pas à calculer une superficie exacte."
    ),
    "description_en": (
        "Potential wetlands across Quebec (MELCC, 2019), assembled from several inventories. Potential location, "
        "with no legal value: it does not replace a detailed field inventory and must not be used to compute an "
        "exact area."
    ),
    "attribution": "© MELCC – DCE (2019)",
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
        "ALTER TABLE quebec_wetland_classes ADD COLUMN outline text CHECK (outline ~ '^#[0-9a-f]{6}$')",
        """
        CREATE TABLE quebec_potential_wetland_classes (
            code text PRIMARY KEY,
            color text NOT NULL CHECK (color ~ '^#[0-9a-f]{6}$'),
            outline text CHECK (outline ~ '^#[0-9a-f]{6}$'),
            label_fr text NOT NULL,
            label_en text,
            position integer NOT NULL UNIQUE
        )
        """,
        f"""
        CREATE TABLE quebec_potential_wetlands (
            {", ".join(f'"{column}" text' for column in SOURCE_COLUMNS)},
            geometry geometry(Geometry, 3857) NOT NULL,
            PRIMARY KEY (objectid),
            FOREIGN KEY (classe) REFERENCES quebec_potential_wetland_classes (code) ON UPDATE CASCADE ON DELETE RESTRICT
        )
        """,
        "CREATE INDEX quebec_potential_wetlands_geometry ON quebec_potential_wetlands USING gist (geometry)",
        *_constraints(KINDS, ADDRESSLESS),
    ):
        connection.execute(sa.text(statement))
    seed(connection)


# Séparée de upgrade pour que les tests, qui vident les tables, puissent la rejouer.
def seed(connection: sa.Connection) -> None:
    for position, (code, color, outline, label_fr, label_en) in enumerate(CLASSES, start=1):
        connection.execute(
            sa.text(
                """
                INSERT INTO quebec_potential_wetland_classes (code, color, outline, label_fr, label_en, position)
                VALUES (:code, :color, :outline, :label_fr, :label_en, :position)
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {"code": code, "color": color, "outline": outline, "label_fr": label_fr, "label_en": label_en, "position": position},
        )
    connection.execute(
        sa.text(
            """
            INSERT INTO catalog_layers
                (code, category_id, country, label_fr, label_en, description_fr, description_en, kind, url, params,
                 attribution, legend_url, min_zoom, max_zoom, position)
            SELECT :code, c.id, 'ca', :label_fr, :label_en, :description_fr, :description_en, 'potential-wetlands', NULL,
                   CAST(:params AS jsonb), :attribution, NULL, :min_zoom, :max_zoom,
                   (SELECT coalesce(max(l.position), 0) + 1 FROM catalog_layers l WHERE l.category_id = c.id)
            FROM layer_categories c WHERE c.code = :category
            ON CONFLICT (code) DO NOTHING
            """
        ),
        {**POTENTIAL_WETLANDS, "params": json.dumps(PARAMS)},
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("DELETE FROM catalog_layers WHERE code = :code"), {"code": CODE})
    for statement in (
        "DROP TABLE quebec_potential_wetlands",
        "DROP TABLE quebec_potential_wetland_classes",
        "ALTER TABLE quebec_wetland_classes DROP COLUMN outline",
        *_constraints(KINDS_BEFORE, ADDRESSLESS_BEFORE),
    ):
        connection.execute(sa.text(statement))
