"""Installations classées pour la protection de l'environnement (ICPE) en base, à la place du flux WMS de
Géorisques (demande du responsable du projet du 19/11/2026, sur le modèle des servitudes SUP de la migration 0054 ;
ADR-0075 du front).

La couche « Installations classées (ICPE) » (fr-georisques-icpe) affichait le WMS INSTALLATIONS_CLASSEES_SIMPLIFIE
de Géorisques. Ses installations viennent désormais de l'extrait ICPE.gpkg (136 194 points au 18/11/2026, une
seule table), importé dans une table dédiée par app/domains/layer_catalog/icpe.py (procédure dans
docs/couches/couches-en-base.md), et servies en tuiles vectorielles (MVT) par la route des tuiles du catalogue.
La même table sert le tableau « Sites ICPE » de l'enquête (POST /fr/environment/icpe-sites).

Même forme que les autres tables de sites, pour partager l'import, la tuile et la recherche dans un rayon : shape
(toujours point ici). Le fichier n'a pas de code_metier : la clé est (shape, code_aiot), le code AIOT de
l'installation, unique dans le fichier. Toutes les colonnes du fichier sont gardées, en texte sous leur nom
d'origine (SOURCE_COLUMNS) ; une chaîne vide devient NULL. geometry est en EPSG:3857.

La couche passe au type icpe, sans adresse ni image de légende : couleur par catégorie de la légende de Géorisques
(params.classes, colonne legende du fichier), contour sombre, symbol = point. Le fichier couvre toutes les
installations (régime, état d'activité), pas seulement celles soumises à autorisation : la description change.
Zoom minimal relevé de 8 à MIN_ZOOM : plus de 136 000 points (mesures dans l'ADR-0075).

Retour arrière : la couche redevient le WMS de Géorisques, la table est supprimée.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None

CODE = "fr-georisques-icpe"

SOURCE_COLUMNS = (
    "gml_id", "code_aiot", "num_siret", "raison_sociale", "adresse", "code_insee", "code_postal", "commune",
    "etat_activite", "activite_principale", "seveso", "regime_vig", "priorite_nationale", "ied", "bovins", "porcs",
    "volailles", "carriere", "eolienne", "industrie", "maille", "date_scraping", "legende", "url_fiche",
)

KINDS_BEFORE = (
    "wms", "wmts", "xyz", "vector", "wfs", "geojson", "database", "database-tiles", "bss", "casias", "wetlands",
    "potential-wetlands", "basol", "sis", "polluting-facilities", "sup",
)
ADDRESSLESS_BEFORE = (
    "database", "database-tiles", "bss", "casias", "wetlands", "potential-wetlands", "basol", "sis",
    "polluting-facilities", "sup",
)
KINDS = (*KINDS_BEFORE, "icpe")
ADDRESSLESS = (*ADDRESSLESS_BEFORE, "icpe")

OTHER = "#969696"


def category(value, color, label_fr, label_en):
    return {"value": value, "color": color, "label": {"fr": label_fr, "en": label_en}}


PARAMS = {
    "color": OTHER,
    "outline": "#3f3f3f",
    "symbol": "point",
    "classes": {
        "property": "legende",
        "values": [
            category("Usine Seveso", "#d7191c", "Usine Seveso", "Seveso plant"),
            category("Usine non Seveso", "#fdae61", "Usine non Seveso", "Non-Seveso plant"),
            category("Carrière", "#8c510a", "Carrière", "Quarry"),
            category("Eolienne", "#2c7bb6", "Éolienne", "Wind turbine"),
            category("Elevage de porc", "#f781bf", "Élevage de porcs", "Pig farm"),
            category("Elevage de volaille", "#e6ab02", "Élevage de volailles", "Poultry farm"),
            category("Elevage de bovin", "#1a9641", "Élevage de bovins", "Cattle farm"),
            category("Autres", OTHER, "Autres installations", "Other installations"),
        ],
    },
}
MIN_ZOOM = 11
DESCRIPTION = {
    "fr": "Installations classées pour la protection de l'environnement : usines (dont Seveso), carrières, éoliennes, élevages.",
    "en": "Installations classified for environmental protection: plants (including Seveso), quarries, wind turbines, farms.",
}

WMS_URL = "https://georisques.gouv.fr/services"
WMS_LAYER = "INSTALLATIONS_CLASSEES_SIMPLIFIE"
WMS_MIN_ZOOM = 8
WMS_DESCRIPTION = {
    "fr": "ICPE soumises à autorisation ou Seveso, hors cessation d'activité.",
    "en": "Classified installations under authorisation or Seveso, still active.",
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
        f"""
        CREATE TABLE icpe_sites (
            shape text NOT NULL CHECK (shape IN ('point', 'polygon')),
            {", ".join(f'"{column}" text' for column in SOURCE_COLUMNS)},
            geometry geometry(Geometry, 3857) NOT NULL,
            PRIMARY KEY (shape, code_aiot)
        )
        """,
        "CREATE INDEX icpe_sites_geometry ON icpe_sites USING gist (geometry)",
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
            SET kind = 'icpe', url = NULL, params = CAST(:params AS jsonb), legend_url = NULL, min_zoom = :min_zoom,
                description_fr = :description_fr, description_en = :description_en, updated_at = now()
            WHERE code = :code
            """
        ),
        {
            "code": CODE,
            "params": json.dumps(PARAMS, ensure_ascii=False),
            "min_zoom": MIN_ZOOM,
            "description_fr": DESCRIPTION["fr"],
            "description_en": DESCRIPTION["en"],
        },
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE catalog_layers
            SET kind = 'wms', url = :url, params = CAST(:params AS jsonb), legend_url = :legend_url, min_zoom = :min_zoom,
                description_fr = :description_fr, description_en = :description_en, updated_at = now()
            WHERE code = :code
            """
        ),
        {
            "code": CODE,
            "url": WMS_URL,
            "params": json.dumps({"format": "image/png", "layers": WMS_LAYER, "version": "1.3.0"}),
            "min_zoom": WMS_MIN_ZOOM,
            "legend_url": f"{WMS_URL}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetLegendGraphic&FORMAT=image/png&LAYER={WMS_LAYER}&SLD_VERSION=1.1.0",
            "description_fr": WMS_DESCRIPTION["fr"],
            "description_en": WMS_DESCRIPTION["en"],
        },
    )
    for statement in ("DROP TABLE icpe_sites", *_constraints(KINDS_BEFORE, ADDRESSLESS_BEFORE)):
        connection.execute(sa.text(statement))
