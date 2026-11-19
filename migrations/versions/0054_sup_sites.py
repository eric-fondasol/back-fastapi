"""Servitudes d'utilité publique liées à la pollution des sols (SUP) en base (demande du responsable du projet du
19/11/2026, sur le modèle des secteurs SIS de la migration 0052 ; ADR-0074 du front).

Le catalogue n'avait pas de couche SUP. Elle est créée dans la catégorie « environnement », juste après les
secteurs SIS (les couches suivantes descendent d'un rang). Ses servitudes viennent de l'extrait SUP.gpkg
(888 emprises au 17/11/2026, une seule table, sans points), importé dans une table dédiée par
app/domains/layer_catalog/sup.py (procédure dans docs/couches/couches-en-base.md), et servies en tuiles
vectorielles (MVT) par la route des tuiles du catalogue.

Même forme que sis_sites, pour partager l'import et la tuile : shape (toujours polygon ici), clé
(shape, code_metier). Le fichier répète une servitude sur plusieurs communes (35 lignes, même géométrie) :
l'import garde la première ligne du fichier. Toutes les colonnes du fichier sont gardées, en texte sous leur nom
d'origine (SOURCE_COLUMNS) ; une chaîne vide devient NULL. geometry est en EPSG:3857.

Type de couche sup, sans adresse ni image de légende : vert d'eau (#018571), pour la distinguer de CASIAS (bleu),
BASOL (rouge), SIS (violet) et des établissements pollueurs (orange). Zoom minimal 12, comme SIS.

Retour arrière : la couche et la table sont supprimées, les couches suivantes remontent d'un rang.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None

CODE = "fr-georisques-sup"
AFTER = "fr-georisques-sis"

SOURCE_COLUMNS = (
    "gml_id", "id_classification", "id_instruction", "code_metier", "id_inventaire_classification",
    "nom_etablissement", "date_ap", "adresse", "code_postal", "code_insee", "nom_commune", "code_departement",
    "code_region", "date_saisie_commune", "x_wgs84", "y_wgs84", "maille", "date_scraping", "url_fiche",
)

KINDS_BEFORE = (
    "wms", "wmts", "xyz", "vector", "wfs", "geojson", "database", "database-tiles", "bss", "casias", "wetlands",
    "potential-wetlands", "basol", "sis", "polluting-facilities",
)
ADDRESSLESS_BEFORE = (
    "database", "database-tiles", "bss", "casias", "wetlands", "potential-wetlands", "basol", "sis",
    "polluting-facilities",
)
KINDS = (*KINDS_BEFORE, "sup")
ADDRESSLESS = (*ADDRESSLESS_BEFORE, "sup")

LAYER = {
    "code": CODE,
    "label_fr": "Servitudes d'utilité publique liées à la pollution des sols (SUP)",
    "label_en": "Public utility easements for soil pollution (SUP)",
    "description_fr": "Terrains pollués grevés d'une servitude d'utilité publique qui en restreint l'usage.",
    "description_en": "Polluted land subject to a public utility easement restricting its use.",
    "attribution": "© Géorisques – MTE / BRGM",
    "min_zoom": 12,
    "max_zoom": 19,
}
PARAMS = {"color": "#018571"}


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
        CREATE TABLE sup_sites (
            shape text NOT NULL CHECK (shape IN ('point', 'polygon')),
            {", ".join(f'"{column}" text' for column in SOURCE_COLUMNS)},
            geometry geometry(Geometry, 3857) NOT NULL,
            PRIMARY KEY (shape, code_metier)
        )
        """,
        "CREATE INDEX sup_sites_geometry ON sup_sites USING gist (geometry)",
        *_constraints(KINDS, ADDRESSLESS),
    ):
        connection.execute(sa.text(statement))
    seed(connection)


# Séparée de upgrade pour que les tests, qui vident les tables, puissent la rejouer. Sans la couche SIS (base de
# test partielle), la couche SUP prend le rang suivant le dernier de la catégorie.
def seed(connection: sa.Connection) -> None:
    connection.execute(
        sa.text(
            """
            UPDATE catalog_layers l SET position = l.position + 1
            FROM catalog_layers after
            WHERE after.code = :after AND l.category_id = after.category_id AND l.position > after.position
            """
        ),
        {"after": AFTER},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO catalog_layers
                (code, category_id, country, label_fr, label_en, description_fr, description_en, kind, url, params,
                 attribution, legend_url, min_zoom, max_zoom, position)
            SELECT :code, c.id, 'fr', :label_fr, :label_en, :description_fr, :description_en, 'sup', NULL,
                   CAST(:params AS jsonb), :attribution, NULL, :min_zoom, :max_zoom,
                   coalesce(
                       (SELECT after.position + 1 FROM catalog_layers after WHERE after.code = :after AND after.category_id = c.id),
                       (SELECT coalesce(max(l.position), 0) + 1 FROM catalog_layers l WHERE l.category_id = c.id)
                   )
            FROM layer_categories c WHERE c.code = 'environnement'
            ON CONFLICT (code) DO NOTHING
            """
        ),
        {**LAYER, "after": AFTER, "params": json.dumps(PARAMS)},
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            WITH removed AS (DELETE FROM catalog_layers WHERE code = :code RETURNING category_id, position)
            UPDATE catalog_layers l SET position = l.position - 1
            FROM removed WHERE l.category_id = removed.category_id AND l.position > removed.position
            """
        ),
        {"code": CODE},
    )
    for statement in ("DROP TABLE sup_sites", *_constraints(KINDS_BEFORE, ADDRESSLESS_BEFORE)):
        connection.execute(sa.text(statement))
