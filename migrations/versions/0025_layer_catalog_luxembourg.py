"""Couches du Luxembourg ajoutées au catalogue : cadastre, topographie, eau de surface et souterraine,
géologie, géothermie et environnement (liste fournie par le métier le 02/11/2026).

Écarts avec la liste, vérifiés le 02/11/2026 sur les capacités WMS de wms.geoportail.lu et de
wmts1.geoportail.lu/opendata :
- Cours d'eau : la liste donnait la couche « A_VERIFIER » ; c'est la couche 749 « Cours d'eau ».
- Plan cadastral : rangé dans « Cadastre et foncier », comme les cadastres de la France et du Québec,
  et non dans « Topographie ».
- Carte géologique harmonisée : déjà au catalogue sous lu-geologie (migration 0007), code que citent
  favoris, « Mes couches » et versions d'enquête. La couche est mise à jour avec les valeurs de la
  liste (couche 2167 au lieu de 2167_1, la même dans un autre thème du géoportail) plutôt que doublée.
- Plan cadastral, orthophoto et carte 1:5000 : sans légende, le service opendata répond 404 à
  GetLegendGraphic.

Les codes passent en minuscules à tirets (contrainte de la table) ; position suit l'ordre de la liste,
après les couches déjà rangées dans la même catégorie.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

OPENDATA_URL = "https://wmts1.geoportail.lu/opendata/service"
PUBLIC_URL = "https://wms.geoportail.lu/public_map_layers/service"

ACT = "© ACT – geoportail.lu"
AGE = "© AGE – geoportail.lu"
SGL = "© Service géologique de l’État (PCH) – geoportail.lu"
AEV = "© Administration de l’environnement – geoportail.lu"

GEOLOGY_CODE = "lu-geologie"


def wms(code, category, label, description, url, layer, attribution, zooms, legend=True):
    legend_url = (
        f"{url}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetLegendGraphic&FORMAT=image/png&LAYER={layer}&SLD_VERSION=1.1.0"
        if legend
        else None
    )
    (label_fr, label_en), (description_fr, description_en), (min_zoom, max_zoom) = label, description, zooms
    return {
        "code": code,
        "category": category,
        "label_fr": label_fr,
        "label_en": label_en,
        "description_fr": description_fr,
        "description_en": description_en,
        "url": url,
        "params": {"layers": layer, "format": "image/png", "version": "1.3.0"},
        "attribution": attribution,
        "legend_url": legend_url,
        "min_zoom": min_zoom,
        "max_zoom": max_zoom,
    }


def flood(code, label_fr, label_en, scenario_fr, scenario_en, layer):
    return wms(
        code,
        "eau-surface",
        (f"Zones inondables - {label_fr}", f"Flood areas - {label_en}"),
        (
            f"Directive Inondation : zones inondables et hauteurs d’eau pour une {scenario_fr}.",
            f"Floods Directive: flood extent and water depth for {scenario_en}.",
        ),
        PUBLIC_URL,
        layer,
        AGE,
        (10, 19),
    )


LAYERS = [
    wms(
        "lu-act-parcelles-cadastrales",
        "cadastre",
        ("Plan cadastral", "Cadastral map"),
        (
            "Plan cadastral numérisé (PCN) : limites des parcelles cadastrales du Grand-Duché.",
            "Digitised cadastral map (PCN): cadastral parcel boundaries of the Grand Duchy.",
        ),
        OPENDATA_URL,
        "parcels",
        ACT,
        (13, 20),
        legend=False,
    ),
    wms(
        "lu-act-orthophoto",
        "topographie",
        ("Orthophoto (dernier millésime)", "Orthophoto (latest edition)"),
        (
            "Orthophotos officielles du Luxembourg, dernier millésime disponible (la version « curseur temporel » "
            "du géoportail regroupe les millésimes 1967-2025, disponibles un par un sous ortho_AAAA).",
            "Official Luxembourg orthophotos, latest edition (the geoportal time-slider groups editions 1967-2025, "
            "available individually as ortho_YYYY).",
        ),
        OPENDATA_URL,
        "ortho_latest",
        ACT,
        (8, 20),
        legend=False,
    ),
    wms(
        "lu-act-topo-5k",
        "topographie",
        ("Carte topographique 1:5000", "Topographic map 1:5,000"),
        ("Carte topographique de base au 1/5 000 (ACT).", "Base topographic map at 1:5,000 (ACT)."),
        OPENDATA_URL,
        "topo_5k",
        ACT,
        (13, 19),
        legend=False,
    ),
    wms(
        "lu-age-cours-eau",
        "eau-surface",
        ("Cours d’eau", "Watercourses"),
        (
            "Cours d’eau de surface du Grand-Duché de Luxembourg (AGE).",
            "Surface watercourses of the Grand Duchy of Luxembourg (AGE).",
        ),
        PUBLIC_URL,
        "749",
        AGE,
        (8, 19),
    ),
    wms(
        "lu-age-hq-extreme",
        "eau-surface",
        ("Zones inondables - crue extrême (HQ extrême, RGD)", "Flood areas - extreme flood (HQ extreme, RGD)"),
        (
            "Directive Inondation : zones inondables et hauteurs d’eau pour une crue extrême, cartes rendues "
            "obligatoires par règlement grand-ducal.",
            "Floods Directive: flood extent and water depth for an extreme flood, maps made binding by Grand-Ducal "
            "regulation.",
        ),
        PUBLIC_URL,
        "3263",
        AGE,
        (10, 19),
    ),
    flood("lu-age-hq100", "crue centennale (HQ100, RGD)", "100-year flood (HQ100, RGD)", "crue centennale (RGD)", "a 100-year flood (RGD)", "3262"),
    flood("lu-age-hq10", "crue décennale (HQ10, RGD)", "10-year flood (HQ10, RGD)", "crue décennale (RGD)", "a 10-year flood (RGD)", "3261"),
    wms(
        "lu-age-zps-rgd",
        "eau-souterraine",
        (
            "Zones de protection d’eau potable (ZPS) - règlement grand-ducal",
            "Drinking water protection zones (ZPS) - Grand-Ducal regulation",
        ),
        (
            "Zones de protection des sources et forages d’eau potable créées par règlement grand-ducal.",
            "Protection zones around drinking-water springs and boreholes established by Grand-Ducal regulation.",
        ),
        PUBLIC_URL,
        "573",
        AGE,
        (8, 19),
    ),
    wms(
        "lu-age-geoth-admissibilite",
        "geothermie",
        ("Admissibilité pour forages géothermiques de faible profondeur", "Shallow geothermal drilling admissibility"),
        (
            "Restrictions à la faisabilité des forages géothermiques de faible profondeur du point de vue de la "
            "protection des eaux souterraines (AGE).",
            "Restrictions on the feasibility of shallow geothermal drilling with regard to groundwater protection (AGE).",
        ),
        PUBLIC_URL,
        "2396",
        AGE,
        (8, 18),
    ),
    wms(
        "lu-aev-casipo",
        "environnement",
        ("Cadastre des sites potentiellement pollués (CASIPO)", "Register of potentially contaminated sites (CASIPO)"),
        (
            "Sites sur lesquels une activité a pu contaminer le sol ; une inscription ne signifie pas que le site "
            "est pollué (AEV).",
            "Sites where an activity may have contaminated the soil; being listed does not mean the site is "
            "polluted (AEV).",
        ),
        PUBLIC_URL,
        "1362",
        AEV,
        (12, 19),
    ),
]

GEOLOGY = wms(
    GEOLOGY_CODE,
    "geologie",
    ("Carte géologique harmonisée", "Harmonised geological map"),
    (
        "Carte géologique vectorielle harmonisée entre feuilles (Service géologique de l’État). Affichage "
        "recommandé à 50 % d’opacité.",
        "Vector geological map harmonised across sheets (State Geological Survey). Recommended display at 50% "
        "opacity.",
    ),
    PUBLIC_URL,
    "2167",
    SGL,
    (9, 18),
)

GEOLOGY_BEFORE = {
    "label_fr": "Carte géologique harmonisée",
    "label_en": "Harmonized geological map",
    "description_fr": "Carte géologique harmonisée du Luxembourg, geoportail.lu.",
    "description_en": "Harmonized geological map of Luxembourg, geoportail.lu.",
    "params": {"layers": "2167_1"},
    "attribution": "© geoportail.lu",
    "legend_url": (
        "https://wms.geoportail.lu/public_map_layers/service?format=image%2Fpng&layer=2167_1&sld_version=1.1.0"
        "&request=GetLegendGraphic&service=WMS&version=1.1.1&styles="
    ),
    "min_zoom": None,
    "max_zoom": None,
}

UPDATE_GEOLOGY = sa.text(
    """
    UPDATE catalog_layers
    SET label_fr = :label_fr, label_en = :label_en, description_fr = :description_fr,
        description_en = :description_en, params = CAST(:params AS jsonb), attribution = :attribution,
        legend_url = :legend_url, min_zoom = :min_zoom, max_zoom = :max_zoom, updated_at = now()
    WHERE code = :code
    """
)


def upgrade() -> None:
    seed(op.get_bind())


# Séparée de upgrade pour que les tests, qui vident les tables, puissent la rejouer.
def seed(connection: sa.Connection) -> None:
    for layer in LAYERS:
        connection.execute(
            sa.text(
                """
                INSERT INTO catalog_layers
                    (code, category_id, country, label_fr, label_en, description_fr, description_en, kind, url, params,
                     attribution, legend_url, min_zoom, max_zoom, position)
                SELECT :code, c.id, 'lu', :label_fr, :label_en, :description_fr, :description_en, 'wms', :url,
                       CAST(:params AS jsonb), :attribution, :legend_url, :min_zoom, :max_zoom,
                       (SELECT coalesce(max(l.position), 0) + 1 FROM catalog_layers l WHERE l.category_id = c.id)
                FROM layer_categories c WHERE c.code = :category
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {**layer, "params": json.dumps(layer["params"])},
        )
    connection.execute(UPDATE_GEOLOGY, {**GEOLOGY, "params": json.dumps(GEOLOGY["params"])})


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("DELETE FROM catalog_layers WHERE code = ANY(:codes)"),
        {"codes": [layer["code"] for layer in LAYERS]},
    )
    connection.execute(UPDATE_GEOLOGY, {**GEOLOGY_BEFORE, "code": GEOLOGY_CODE, "params": json.dumps(GEOLOGY_BEFORE["params"])})
