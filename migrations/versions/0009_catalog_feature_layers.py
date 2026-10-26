"""Couches vectorielles du catalogue (ADR-0045 du front) : types wfs et geojson, interrogés par le back
(GET /layer-catalog/{code}/features) et dessinés par le front en GeoJSON.

Le back appelle lui-même ces services : une URL en http:// est donc admise pour ces deux types
(ws.carmencarto.fr refuse le HTTPS), jamais pour une couche d'images, chargée par le navigateur.

Ajoute les 10 couches WFS et GeoJSON de la liste du métier du 23/10/2026, écartées par la 0008.
Zoom minimal relevé à 8 au moins, et à 9 pour les couches les plus lourdes (ZSC/SIC, ZPS, espaces
naturels sensibles, réserves de biosphère) : mesuré le 23/10/2026, la France entière pèse jusqu'à
84 Mo de GML et un écran au zoom 9 jusqu'à 3 Mo. Piézomètres à partir du zoom 10 : Hub'Eau compte
plus de 4 000 stations sur un écran de Paris au zoom 9, au-delà du plafond d'objets du back.

params.axisOrder = "latlon" : ws.carmencarto.fr (MapServer, WFS 1.1.0, EPSG:4326) attend la BBOX et
rend les coordonnées en latitude, longitude.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

INPN_URL = "http://ws.carmencarto.fr/WFS/119/fxx_inpn"
INPN = "© INPN – PatriNat (OFB, MNHN, CNRS, IRD)"


def inpn(code, label, description, type_name, min_zoom):
    return {
        "code": code,
        "category": "environnement",
        "label": label,
        "description": description,
        "kind": "wfs",
        "url": INPN_URL,
        "params": {"typeName": type_name, "version": "1.1.0", "outputFormat": "GML2", "srsName": "EPSG:4326", "axisOrder": "latlon"},
        "attribution": INPN,
        "zooms": (min_zoom, 18),
    }


LAYERS = [
    {
        "code": "fr-ades-piezometres",
        "category": "eau-souterraine",
        "label": ("Points d'eau ADES - piézomètres", "ADES water points - piezometers"),
        "description": (
            "Stations de mesure du niveau des nappes (piézomètres), via l'API Hub'Eau Piézométrie.",
            "Groundwater level monitoring stations (piezometers), via Hub'Eau API.",
        ),
        "kind": "geojson",
        "url": "https://hubeau.eaufrance.fr/api/v1/niveaux_nappes/stations",
        "params": {"format": "geojson", "size": 20000, "bbox": "{bbox}"},
        "attribution": "© ADES / BRGM – Hub'Eau",
        "zooms": (10, 19),
    },
    {
        "code": "fr-clc-2018",
        "category": "environnement",
        "label": ("CORINE Land Cover 2018", "CORINE Land Cover 2018"),
        "description": ("Occupation des sols 2018 en 44 postes (Copernicus / SDES).", "2018 land cover, 44 classes (Copernicus / SDES)."),
        "kind": "wfs",
        "url": "https://data.geopf.fr/wfs/ows",
        "params": {"typeName": "LANDCOVER.CLC18_FR:clc18_fr", "version": "2.0.0", "outputFormat": "application/json", "srsName": "EPSG:4326"},
        "attribution": "© Copernicus / SDES – diffusion IGN",
        "zooms": (12, 18),
    },
    inpn(
        "fr-inpn-appb",
        ("Arrêtés de protection de biotope / habitats naturels", "Biotope / natural habitat protection orders"),
        (
            "Périmètres des arrêtés préfectoraux de protection (biotopes, habitats naturels).",
            "Prefectoral protection order perimeters (biotopes, natural habitats).",
        ),
        "Arretes_de_protection_d_habitats_naturels",
        8,
    ),
    inpn(
        "fr-inpn-ens",
        ("Espaces naturels sensibles", "Sensitive natural areas"),
        ("Espaces naturels sensibles des départements.", "Departmental sensitive natural areas."),
        "Espaces_naturels_sensibles",
        9,
    ),
    inpn(
        "fr-inpn-natura2000-zsc-sic",
        ("Natura 2000 - Directive Habitats (ZSC/SIC)", "Natura 2000 - Habitats Directive (SAC/SCI)"),
        (
            "Zones spéciales de conservation et sites d'importance communautaire.",
            "Special areas of conservation and sites of community importance.",
        ),
        "Sites_d_importance_communautaire_JOUE__ZSC_SIC_",
        9,
    ),
    inpn(
        "fr-inpn-natura2000-zps",
        ("Natura 2000 - Directive Oiseaux (ZPS)", "Natura 2000 - Birds Directive (SPA)"),
        ("Zones de protection spéciale.", "Special protection areas."),
        "Zones_de_protection_speciale",
        9,
    ),
    inpn(
        "fr-inpn-rnn",
        ("Réserves naturelles nationales", "National nature reserves"),
        ("Périmètres des réserves naturelles nationales.", "National nature reserve perimeters."),
        "Reserves_Naturelles_Nationales",
        8,
    ),
    inpn(
        "fr-inpn-biosphere",
        ("Réserves de biosphère", "Biosphere reserves"),
        ("Réserves de biosphère (programme MAB UNESCO).", "Biosphere reserves (UNESCO MAB programme)."),
        "Reserves_de_la_biosphere",
        9,
    ),
    inpn(
        "fr-inpn-ramsar",
        ("Sites Ramsar", "Ramsar sites"),
        (
            "Zones humides d'importance internationale (convention de Ramsar).",
            "Wetlands of international importance (Ramsar Convention).",
        ),
        "Sites_Ramsar",
        8,
    ),
    inpn(
        "fr-inpn-zico",
        ("Zones importantes pour la conservation des oiseaux (ZICO)", "Important bird areas (IBA/ZICO)"),
        ("Inventaire des ZICO.", "Important Bird Areas inventory."),
        "ZICO",
        8,
    ),
]


def upgrade() -> None:
    op.execute("ALTER TABLE catalog_layers DROP CONSTRAINT IF EXISTS catalog_layers_kind_check")
    op.execute(
        "ALTER TABLE catalog_layers ADD CONSTRAINT catalog_layers_kind_check "
        "CHECK (kind IN ('wms', 'wmts', 'xyz', 'vector', 'wfs', 'geojson'))"
    )
    op.execute("ALTER TABLE catalog_layers DROP CONSTRAINT IF EXISTS catalog_layers_url_check")
    op.execute(
        "ALTER TABLE catalog_layers ADD CONSTRAINT catalog_layers_url_check "
        "CHECK (url LIKE 'https://%' OR (kind IN ('wfs', 'geojson') AND url LIKE 'http://%'))"
    )
    seed(op.get_bind())


# Séparée de upgrade pour que les tests, qui vident les tables, puissent la rejouer.
def seed(connection: sa.Connection) -> None:
    for layer in LAYERS:
        (label_fr, label_en), (description_fr, description_en), (min_zoom, max_zoom) = layer["label"], layer["description"], layer["zooms"]
        connection.execute(
            sa.text(
                """
                INSERT INTO catalog_layers
                    (code, category_id, country, label_fr, label_en, description_fr, description_en, kind, url, params,
                     attribution, min_zoom, max_zoom, position)
                SELECT :code, c.id, 'fr', :label_fr, :label_en, :description_fr, :description_en, :kind, :url,
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
                "url": layer["url"],
                "params": json.dumps(layer["params"]),
                "attribution": layer["attribution"],
                "min_zoom": min_zoom,
                "max_zoom": max_zoom,
            },
        )


def downgrade() -> None:
    op.execute("DELETE FROM catalog_layers WHERE kind IN ('wfs', 'geojson')")
    op.execute("ALTER TABLE catalog_layers DROP CONSTRAINT IF EXISTS catalog_layers_url_check")
    op.execute("ALTER TABLE catalog_layers ADD CONSTRAINT catalog_layers_url_check CHECK (url LIKE 'https://%')")
    op.execute("ALTER TABLE catalog_layers DROP CONSTRAINT IF EXISTS catalog_layers_kind_check")
    op.execute("ALTER TABLE catalog_layers ADD CONSTRAINT catalog_layers_kind_check CHECK (kind IN ('wms', 'wmts', 'xyz', 'vector'))")
