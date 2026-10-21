"""Catalogue des couches de la carte, partagé par tous et rangé par pays (ADR-0043 du front).

Reprend les six couches et les deux catégories jusque-là écrites dans le front, avec leurs codes
(fr-geologie…) : favoris, « Mes couches » et versions d'enquête les citent.

params dépend du type : layers (WMS) ; layer, style, tileMatrixSet (WMTS) ; tileSize et
fullScaleZoom (XYZ servi par un export ArcGIS) ; municipalityTiles (vecteur). renderer désigne un
rendu écrit dans le front : cadastre (tuiles vectorielles stylées) ou quebecLots (légende dessinée).
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

CATEGORIES = [
    ("geologie", "Géologie", "Geology", 1),
    ("cadastre", "Cadastre et foncier", "Cadastre and land", 2),
]

QUEBEC_LOTS_TILE_SIZE = 512

LAYERS = [
    {
        "code": "fr-geologie",
        "category": "geologie",
        "country": "fr",
        "label_fr": "Carte géologique (BRGM)",
        "label_en": "Geological map (BRGM)",
        "description_fr": "Cartes géologiques du BRGM, service WMS « GEOLOGIE ». Pas de légende fournie par le service.",
        "description_en": 'BRGM geological maps, "GEOLOGIE" WMS service. No legend provided by the service.',
        "kind": "wms",
        "url": "https://geoservices.brgm.fr/geologie",
        "params": {"layers": "GEOLOGIE"},
        "attribution": "© BRGM",
        "legend_url": None,
        "min_zoom": None,
        "max_zoom": None,
        "renderer": None,
        "position": 1,
    },
    {
        "code": "fr-cadastre",
        "category": "cadastre",
        "country": "fr",
        "label_fr": "Cadastre (IGN)",
        "label_en": "Cadastre (IGN)",
        "description_fr": "Parcellaire Express (PCI) de l'IGN, Géoplateforme. Limites de communes dès le zoom 12, parcelles à partir du zoom 15.",
        "description_en": "IGN Parcellaire Express (PCI), Géoplateforme. Municipal boundaries from zoom 12, parcels from zoom 15.",
        "kind": "wmts",
        "url": "https://data.geopf.fr/wmts",
        "params": {"layer": "CADASTRALPARCELS.PARCELLAIRE_EXPRESS", "style": "PCI vecteur", "tileMatrixSet": "PM_0_19"},
        "attribution": "© IGN",
        "legend_url": "https://data.geopf.fr/annexes/ressources/legendes/CADASTRALPARCELS.PARCELLAIRE_EXPRESS-legend.png",
        "min_zoom": 12,
        "max_zoom": 19,
        "renderer": None,
        "position": 1,
    },
    {
        "code": "fr-cadastre-etalab",
        "category": "cadastre",
        "country": "fr",
        "label_fr": "Cadastre interactif (Etalab)",
        "label_en": "Interactive land registry (Etalab)",
        "description_fr": (
            "Communes, sections et parcelles du cadastre Etalab (DINUM), en tuiles vectorielles, comme le cadastre de "
            "l'IGN : communes jusqu'au zoom 13, sections et leurs codes de 13 à 15, parcelles et leurs numéros dès 15. "
            "La parcelle survolée est mise en évidence."
        ),
        "description_en": (
            "Municipalities, sections and parcels of the Etalab land registry (DINUM), as vector tiles, like the IGN "
            "land registry: municipalities up to zoom 13, sections and their codes from 13 to 15, parcels and their "
            "numbers from 15. The hovered parcel is highlighted."
        ),
        "kind": "vector",
        "url": "https://openmaptiles.geo.data.gouv.fr/data/cadastre/{z}/{x}/{y}.pbf",
        "params": {"municipalityTiles": "https://openmaptiles.geo.data.gouv.fr/data/decoupage-administratif/{z}/{x}/{y}.pbf"},
        "attribution": "© DINUM (data.gouv.fr), cadastre Etalab",
        "legend_url": None,
        "min_zoom": 10,
        "max_zoom": 16,
        "renderer": "cadastre",
        "position": 2,
    },
    {
        "code": "ca-cadastre-lots",
        "category": "cadastre",
        "country": "ca",
        "label_fr": "Lots du cadastre (Québec)",
        "label_en": "Cadastre lots (Québec)",
        "description_fr": "Contours et numéros des lots du cadastre rénové du Québec (cadastre allégé, mis à jour tous les deux mois).",
        "description_en": "Outlines and numbers of the lots of Québec's renovated cadastre (light cadastre, updated every two months).",
        "kind": "xyz",
        "url": (
            "https://geo.environnement.gouv.qc.ca/donnees/rest/services/Reference/Cadastre_allege/MapServer/export"
            "?bbox={bbox-epsg-3857}&bboxSR=3857&imageSR=3857"
            f"&size={QUEBEC_LOTS_TILE_SIZE},{QUEBEC_LOTS_TILE_SIZE}&format=png32&transparent=true&f=image"
        ),
        "params": {"tileSize": QUEBEC_LOTS_TILE_SIZE, "fullScaleZoom": 15},
        "attribution": "© Gouvernement du Québec (cadastre allégé)",
        "legend_url": None,
        "min_zoom": 12,
        "max_zoom": None,
        "renderer": "quebecLots",
        "position": 1,
    },
    {
        "code": "ca-cptaq-demandes",
        "category": "cadastre",
        "country": "ca",
        "label_fr": "Demandes d'autorisation (CPTAQ)",
        "label_en": "Authorization requests (CPTAQ)",
        "description_fr": "Demandes d'autorisation déposées auprès de la Commission de protection du territoire agricole du Québec (polygones).",
        "description_en": "Authorization requests filed with the Québec agricultural land protection commission (polygons).",
        "kind": "wms",
        "url": "https://carto.cptaq.gouv.qc.ca/cgi-bin/v2/cptaq",
        "params": {"layers": "demande"},
        "attribution": "© CPTAQ",
        "legend_url": (
            "https://carto.cptaq.gouv.qc.ca/cgi-bin/v2/cptaq?version=1.3.0&service=WMS&request=GetLegendGraphic"
            "&sld_version=1.1.0&layer=demande&format=image/png&STYLE=default"
        ),
        "min_zoom": 13,
        "max_zoom": None,
        "renderer": None,
        "position": 2,
    },
    {
        "code": "lu-geologie",
        "category": "geologie",
        "country": "lu",
        "label_fr": "Carte géologique harmonisée",
        "label_en": "Harmonized geological map",
        "description_fr": "Carte géologique harmonisée du Luxembourg, geoportail.lu.",
        "description_en": "Harmonized geological map of Luxembourg, geoportail.lu.",
        "kind": "wms",
        "url": "https://wms.geoportail.lu/public_map_layers/service",
        "params": {"layers": "2167_1"},
        "attribution": "© geoportail.lu",
        "legend_url": (
            "https://wms.geoportail.lu/public_map_layers/service?format=image%2Fpng&layer=2167_1&sld_version=1.1.0"
            "&request=GetLegendGraphic&service=WMS&version=1.1.1&styles="
        ),
        "min_zoom": None,
        "max_zoom": None,
        "renderer": None,
        "position": 1,
    },
]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS layer_categories (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE CHECK (code ~ '^[a-z0-9][a-z0-9-]*$'),
            label_fr text NOT NULL,
            label_en text,
            position integer NOT NULL,
            created_at timestamp(0) with time zone NOT NULL DEFAULT now(),
            updated_at timestamp(0) with time zone NOT NULL DEFAULT now(),
            updated_by text
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_layers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE CHECK (code ~ '^[a-z0-9][a-z0-9-]*$'),
            category_id uuid NOT NULL REFERENCES layer_categories (id) ON DELETE RESTRICT,
            country text NOT NULL CHECK (country ~ '^[a-z]{2}$'),
            label_fr text NOT NULL,
            label_en text,
            description_fr text,
            description_en text,
            kind text NOT NULL CHECK (kind IN ('wms', 'wmts', 'xyz', 'vector')),
            url text NOT NULL CHECK (url LIKE 'https://%'),
            params jsonb NOT NULL DEFAULT '{}'::jsonb,
            attribution text NOT NULL,
            legend_url text,
            min_zoom numeric,
            max_zoom numeric,
            renderer text CHECK (renderer IN ('cadastre', 'quebecLots')),
            position integer NOT NULL,
            enabled boolean NOT NULL DEFAULT true,
            created_at timestamp(0) with time zone NOT NULL DEFAULT now(),
            updated_at timestamp(0) with time zone NOT NULL DEFAULT now(),
            updated_by text,
            CONSTRAINT catalog_layers_vector_renderer CHECK ((kind = 'vector') = (renderer IS NOT DISTINCT FROM 'cadastre'))
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_catalog_layers_category ON catalog_layers (category_id, position)")
    seed(op.get_bind())


# Séparée de upgrade pour que les tests, qui vident les tables, puissent la rejouer.
def seed(connection: sa.Connection) -> None:
    for code, label_fr, label_en, position in CATEGORIES:
        connection.execute(
            sa.text(
                """
                INSERT INTO layer_categories (code, label_fr, label_en, position)
                VALUES (:code, :label_fr, :label_en, :position)
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {"code": code, "label_fr": label_fr, "label_en": label_en, "position": position},
        )
    for layer in LAYERS:
        connection.execute(
            sa.text(
                """
                INSERT INTO catalog_layers
                    (code, category_id, country, label_fr, label_en, description_fr, description_en, kind, url, params,
                     attribution, legend_url, min_zoom, max_zoom, renderer, position)
                SELECT :code, id, :country, :label_fr, :label_en, :description_fr, :description_en, :kind, :url,
                       CAST(:params AS jsonb), :attribution, :legend_url, :min_zoom, :max_zoom, :renderer, :position
                FROM layer_categories WHERE code = :category
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {**layer, "params": json.dumps(layer["params"])},
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS catalog_layers")
    op.execute("DROP TABLE IF EXISTS layer_categories")
