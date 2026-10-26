"""Couches de la France ajoutées au catalogue : topographie, eau de surface et souterraine, géologie,
géothermie et environnement (liste fournie par le métier le 23/10/2026).

Écartées de cette liste : les couches WFS (INPN, CORINE Land Cover 2018) et GeoJSON (piézomètres
Hub'Eau), que le front ne sait pas afficher ; le Parcellaire Express, déjà présent sous fr-cadastre ;
le SCAN 25, servi par l'URL privée de la Géoplateforme avec une clé d'API qui serait envoyée à
tous les navigateurs.

Les codes passent en minuscules à tirets (contrainte de la table) ; position suit l'ordre de la liste,
après les couches déjà rangées dans la même catégorie.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

CATEGORIES = [
    ("topographie", "Topographie", "Topography", 3),
    ("eau-surface", "Eau de surface", "Surface water", 4),
    ("eau-souterraine", "Eau souterraine", "Groundwater", 5),
    ("geothermie", "Géothermie", "Geothermal energy", 6),
    ("environnement", "Environnement", "Environment", 7),
]

IGN = "© IGN – Géoplateforme"
SANDRE = "© Sandre / OFB – Eaufrance"
GEORISQUES = "© Géorisques – MTE / BRGM"
BRGM = "© BRGM"
GEOTHERMIE = "© BRGM / ADEME – Géothermies.fr"

GEORISQUES_URL = "https://georisques.gouv.fr/services"
BRGM_GEOLOGIE_URL = "https://geoservices.brgm.fr/geologie"
BRGM_REFERENTIEL_URL = "https://mapsref.brgm.fr/wxs/referentiel/geologie"
GEOTHERMIE_URL = "https://geoservices.brgm.fr/geothermie"


def wms(code, category, label, description, url, layer, attribution, zooms, version="1.3.0"):
    legend = (
        f"{url}?SERVICE=WMS&VERSION={version}&REQUEST=GetLegendGraphic&FORMAT=image/png&LAYER={layer}&SLD_VERSION=1.1.0"
    )
    return {
        "code": code,
        "category": category,
        "label": label,
        "description": description,
        "kind": "wms",
        "url": url,
        "params": {"layers": layer, "format": "image/png", "version": version},
        "attribution": attribution,
        "legend_url": legend,
        "zooms": zooms,
    }


def wmts(code, category, label, description, layer, style, tile_matrix_set, image_format, zooms, attribution=IGN, legend_url=None):
    return {
        "code": code,
        "category": category,
        "label": label,
        "description": description,
        "kind": "wmts",
        "url": "https://data.geopf.fr/wmts",
        "params": {"layer": layer, "style": style, "tileMatrixSet": tile_matrix_set, "format": image_format},
        "attribution": attribution,
        "legend_url": legend_url,
        "zooms": zooms,
    }


def gmi(loop, depth_fr, depth_en, low, high):
    loop_fr, loop_en = {"ferme": ("échangeur fermé (sonde)", "closed loop"), "ouvert": ("échangeur ouvert (nappe)", "open loop")}[loop]
    short_fr = {"ferme": "sondes", "ouvert": "nappe"}[loop]
    first = (loop, low) == ("ferme", 10)
    name_fr = "géothermie de minime importance (vert/orange/rouge)" if first else "GMI"
    colors_en = " (green/orange/red)" if first else ""
    return wms(
        f"fr-brgm-gmi-{loop}-{low}-{high}",
        "geothermie",
        (f"Zones réglementaires GMI - {loop_fr} {depth_fr}", f"GMI regulatory zones - {loop_en} {depth_en}"),
        (
            f"Zonage réglementaire {name_fr}, {short_fr} {low}-{high} m.",
            f"Minor geothermal regulatory zoning{colors_en}, {loop_en} {low}-{high} m.",
        ),
        GEOTHERMIE_URL,
        f"GMI_{loop.upper()}_{low}_{high}",
        GEOTHERMIE,
        (8, 17),
    )


def flood(level, label_fr, label_en, scenario_fr, scenario_en, layer):
    return wms(
        f"fr-georisques-alea-debordement-{level}",
        "eau-surface",
        (f"Surfaces inondables - débordement de cours d'eau, {label_fr}", f"Flood areas - river overflow, {label_en}"),
        (
            f"Directive Inondation (TRI) : synthèse aléa débordement de cours d'eau, scénario {scenario_fr}.",
            f"Floods Directive (TRI): river overflow hazard synthesis, {scenario_en} scenario.",
        ),
        GEORISQUES_URL,
        layer,
        GEORISQUES,
        (10, 18),
    )


LAYERS = [
    wmts(
        "fr-ign-carte-etat-major-40k",
        "topographie",
        ("Carte de l'État-major (1820-1866)", "État-major historical map (1820-1866)"),
        (
            "SCAN État-major 40K : assemblage des minutes d'État-major au 1/40 000 du XIXe siècle.",
            "SCAN État-major 40K: mosaic of 19th-century 1:40,000 French staff maps.",
        ),
        "GEOGRAPHICALGRIDSYSTEMS.ETATMAJOR40",
        "normal",
        "PM_6_15",
        "image/jpeg",
        (6, 15),
    ),
    wms(
        "fr-sandre-sage",
        "eau-souterraine",
        ("Schémas d'Aménagement et de Gestion des Eaux (SAGE)", "Water Development and Management Plans (SAGE)"),
        ("Périmètres des SAGE – France entière (Gest'Eau / Sandre).", "SAGE perimeters – whole of France (Gest'Eau / Sandre)."),
        "https://services.sandre.eaufrance.fr/geo/zpl",
        "Sage",
        SANDRE,
        (5, 16),
    ),
    wms(
        "fr-sandre-zre",
        "eau-souterraine",
        ("Zones de répartition des eaux (ZRE) - Métropole", "Water allocation zones (ZRE) - Mainland France"),
        (
            "Zones présentant une insuffisance chronique des ressources en eau par rapport aux besoins (art. R211-71 C. env.).",
            "Areas with chronic shortage of water resources relative to demand (Environment Code R211-71).",
        ),
        "https://services.sandre.eaufrance.fr/geo/zrpe",
        "ZRE_FXX",
        SANDRE,
        (5, 16),
    ),
    wmts(
        "fr-ign-reseau-hydrographique",
        "eau-surface",
        ("Réseau hydrographique", "Hydrographic network"),
        (
            "Réseau hydrographique issu de la BD TOPO (cours d'eau, surfaces en eau).",
            "Hydrographic network from BD TOPO (rivers, water surfaces).",
        ),
        "HYDROGRAPHY.HYDROGRAPHY",
        "normal",
        "PM_0_18",
        "image/png",
        (6, 18),
    ),
    wms(
        "fr-sandre-stations-hydrometriques",
        "eau-surface",
        ("Stations hydrométriques - Métropole", "Hydrometric stations - Mainland France"),
        (
            "Stations de mesure du débit des cours d'eau (référentiel hydrométrique).",
            "River flow measurement stations (hydrometric reference).",
        ),
        "https://services.sandre.eaufrance.fr/geo/hyd",
        "StationHydro_FXX",
        SANDRE,
        (8, 18),
    ),
    wms(
        "fr-ign-inpe",
        "eau-surface",
        ("Inventaire national des plans d'eau (INPE)", "National inventory of water bodies (INPE)"),
        (
            "Géométrie et description des plans d'eau (IGEDD, IGN, CNES).",
            "Geometry and description of water bodies (IGEDD, IGN, CNES).",
        ),
        "https://data.geopf.fr/wms-v/ows",
        "INPE",
        IGN,
        (10, 18),
    ),
    wmts(
        "fr-clc15-hr-zones-humides-eau",
        "eau-surface",
        (
            "Corine Land Cover haute résolution 2015 - zones humides et surfaces en eau",
            "Corine Land Cover high resolution 2015 - wetlands and water bodies",
        ),
        (
            "Couche haute résolution (raster 20 m) des zones humides et surfaces en eau permanentes/temporaires, millésime "
            "2015, rattachée au jeu CORINE Land Cover (métadonnée MTECT_CORINE-LAND-COVER).",
            "High-resolution (20 m raster) layer of wetlands and permanent/temporary water bodies, 2015, part of the CORINE "
            "Land Cover dataset (metadata MTECT_CORINE-LAND-COVER).",
        ),
        "LANDCOVER.HR.WAW.CLC15",
        "CORINE Land Cover - HR - zones humides et surfaces en eaux permanentes",
        "PM_0_13",
        "image/png",
        (0, 13),
        attribution="© UE Copernicus / SDES (MTECT) – diffusion IGN",
        legend_url=(
            "https://data.geopf.fr/wms-r?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetLegendGraphic&FORMAT=image/png"
            "&LAYER=LANDCOVER.HR.WAW.CLC15"
        ),
    ),
    flood("frequent", "aléa fréquent (décennal)", "frequent hazard (10-year)", "fréquent", "frequent", "ALEA_SYNT_01_01FOR"),
    flood("moyen", "aléa moyen (centennal)", "medium hazard (100-year)", "moyen", "medium", "ALEA_SYNT_01_02MOY"),
    flood("rare", "aléa rare (millénal)", "rare hazard (1000-year)", "extrême", "extreme", "ALEA_SYNT_01_04FAI"),
    wms(
        "fr-brgm-bss-points-eau",
        "eau-souterraine",
        ("Points d'eau de la BSS (nature/profondeur)", "BSS water points (type/depth)"),
        (
            "Référentiel des points d'eau de la Banque du Sous-Sol (BSS Eau).",
            "Water point reference from the French Subsurface Database (BSS Eau).",
        ),
        BRGM_GEOLOGIE_URL,
        "BSS_EAU_POINT",
        BRGM,
        (11, 19),
    ),
    wms(
        "fr-georisques-remontees-nappe",
        "eau-souterraine",
        ("Carte nationale des remontées de nappe", "National groundwater flooding map"),
        (
            "Sensibilité aux inondations par remontée de nappe (BRGM / Géorisques).",
            "Susceptibility to groundwater flooding (BRGM / Géorisques).",
        ),
        GEORISQUES_URL,
        "REMNAPPE_FR",
        GEORISQUES,
        (6, 17),
    ),
    wms(
        "fr-sandre-aac",
        "eau-souterraine",
        ("Aires d'alimentation de captage - Métropole", "Drinking water catchment areas - Mainland France"),
        ("Aires d'alimentation des captages d'eau potable (AAC).", "Drinking-water catchment supply areas (AAC)."),
        "https://services.sandre.eaufrance.fr/geo/zgr",
        "AAC_FXX",
        SANDRE,
        (8, 18),
    ),
    wms(
        "fr-sandre-ouvrages-prelevement",
        "eau-souterraine",
        ("Ouvrages de prélèvement", "Water abstraction structures"),
        ("Ouvrages de prélèvement d'eau (BNPE / Sandre).", "Water abstraction structures (BNPE / Sandre)."),
        "https://services.sandre.eaufrance.fr/geo/prl",
        "OuvragePrel",
        SANDRE,
        (10, 19),
    ),
    wms(
        "fr-brgm-bss-tous-ouvrages",
        "geologie",
        ("Données sur les sols - ouvrages BSS", "Subsurface data - BSS boreholes"),
        (
            "Ensemble des ouvrages de la Banque du Sous-Sol, avec étiquettes.",
            "All French Subsurface Database boreholes, with labels.",
        ),
        BRGM_GEOLOGIE_URL,
        "BSS_TOTAL_AVEC_LABEL",
        BRGM,
        (13, 19),
    ),
    wms(
        "fr-brgm-carte-geol-50k-imprimee",
        "geologie",
        ("Carte géologique imprimée 1/50 000", "Printed geological map 1:50,000"),
        (
            "Scans géoréférencés des cartes géologiques papier au 1/50 000.",
            "Georeferenced scans of the printed 1:50,000 geological maps.",
        ),
        BRGM_REFERENTIEL_URL,
        "SCAN_GEOL50",
        BRGM,
        (9, 17),
        version="1.1.1",
    ),
    wms(
        "fr-brgm-carte-geol-50k-harmonisee",
        "geologie",
        ("Carte géologique 1/50 000 vecteur harmonisée", "Harmonised vector geological map 1:50,000"),
        (
            "BD Charm-50 : cartes géologiques 1/50 000 vectorisées et harmonisées.",
            "BD Charm-50: vectorised and harmonised 1:50,000 geological maps.",
        ),
        BRGM_REFERENTIEL_URL,
        "GEOL50_HARM",
        BRGM,
        (9, 17),
        version="1.1.1",
    ),
    wms(
        "fr-brgm-geoth-installations-ouvert",
        "geothermie",
        ("Installations sur échangeurs ouverts (nappe)", "Open-loop installations (groundwater)"),
        (
            "Installations géothermiques sur nappe (Observatoire de la géothermie de surface).",
            "Open-loop shallow geothermal installations (shallow geothermal observatory).",
        ),
        GEOTHERMIE_URL,
        "INSTALLATIONS_ECHANGEUR_OUVERT",
        GEOTHERMIE,
        (10, 19),
    ),
    wms(
        "fr-brgm-geoth-installations-ferme",
        "geothermie",
        ("Installations sur échangeurs fermés (sonde)", "Closed-loop installations (borehole heat exchangers)"),
        (
            "Installations géothermiques sur sondes (Observatoire de la géothermie de surface).",
            "Closed-loop shallow geothermal installations.",
        ),
        GEOTHERMIE_URL,
        "INSTALLATIONS_ECHANGEUR_FERME",
        GEOTHERMIE,
        (10, 19),
    ),
    gmi("ferme", "10 à 50 m", "10-50 m", 10, 50),
    gmi("ferme", "50 à 100 m", "50-100 m", 50, 100),
    gmi("ferme", "100 à 200 m", "100-200 m", 100, 200),
    gmi("ouvert", "10 à 50 m", "10-50 m", 10, 50),
    gmi("ouvert", "50 à 100 m", "50-100 m", 50, 100),
    gmi("ouvert", "100 à 200 m", "100-200 m", 100, 200),
    wms(
        "fr-georisques-casias-points",
        "environnement",
        ("Sites CASIAS (points)", "CASIAS sites (points)"),
        (
            "Carte des anciens sites industriels et activités de service (ex-BASIAS) - points.",
            "Former industrial sites and service activities (ex-BASIAS) - points.",
        ),
        GEORISQUES_URL,
        "SSP_ETS_GE_POINT",
        GEORISQUES,
        (12, 19),
    ),
    wms(
        "fr-georisques-sis",
        "environnement",
        ("Secteurs d'information sur les sols (SIS)", "Soil information sectors (SIS)"),
        (
            "Terrains où la pollution connue des sols justifie des études et mesures de gestion.",
            "Sites where known soil pollution requires studies and management measures.",
        ),
        GEORISQUES_URL,
        "SSP_CLASSIF_SIS_GE",
        GEORISQUES,
        (12, 19),
    ),
    wms(
        "fr-georisques-casias-polygones",
        "environnement",
        ("Sites CASIAS (polygones)", "CASIAS sites (polygons)"),
        (
            "Anciens sites industriels et activités de service - emprises.",
            "Former industrial sites and service activities - footprints.",
        ),
        GEORISQUES_URL,
        "SSP_ETS_GE_POLYGON",
        GEORISQUES,
        (12, 19),
    ),
    wms(
        "fr-georisques-pollution-instruction-points",
        "environnement",
        (
            "Pollution suspectée ou avérée - information de l'administration (points)",
            "Suspected or proven pollution - administration information (points)",
        ),
        (
            "Sites pollués appelant une action des pouvoirs publics (ex-BASOL) - points.",
            "Polluted sites requiring public action (ex-BASOL) - points.",
        ),
        GEORISQUES_URL,
        "SSP_INSTR_GE_POINT",
        GEORISQUES,
        (12, 19),
    ),
    wms(
        "fr-georisques-pollution-instruction-polygones",
        "environnement",
        (
            "Pollution suspectée ou avérée - information de l'administration (polygones)",
            "Suspected or proven pollution - administration information (polygons)",
        ),
        (
            "Sites pollués appelant une action des pouvoirs publics (ex-BASOL) - emprises.",
            "Polluted sites requiring public action (ex-BASOL) - footprints.",
        ),
        GEORISQUES_URL,
        "SSP_INSTR_GE_POLYGONE",
        GEORISQUES,
        (12, 19),
    ),
    wms(
        "fr-georisques-etablissements-pollueurs",
        "environnement",
        ("Établissements pollueurs", "Polluting facilities"),
        (
            "Établissements déclarant des émissions polluantes (registre IREP).",
            "Facilities reporting pollutant emissions (IREP register).",
        ),
        GEORISQUES_URL,
        "ETABLISSEMENTS_POLLUEURS",
        GEORISQUES,
        (9, 19),
    ),
    wms(
        "fr-georisques-icpe",
        "environnement",
        ("Installations classées (ICPE)", "Classified installations (ICPE)"),
        (
            "ICPE soumises à autorisation ou Seveso, hors cessation d'activité.",
            "Classified installations under authorisation or Seveso, still active.",
        ),
        GEORISQUES_URL,
        "INSTALLATIONS_CLASSEES_SIMPLIFIE",
        GEORISQUES,
        (8, 19),
    ),
]


def upgrade() -> None:
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
        (label_fr, label_en), (description_fr, description_en), (min_zoom, max_zoom) = layer["label"], layer["description"], layer["zooms"]
        connection.execute(
            sa.text(
                """
                INSERT INTO catalog_layers
                    (code, category_id, country, label_fr, label_en, description_fr, description_en, kind, url, params,
                     attribution, legend_url, min_zoom, max_zoom, position)
                SELECT :code, c.id, 'fr', :label_fr, :label_en, :description_fr, :description_en, :kind, :url,
                       CAST(:params AS jsonb), :attribution, :legend_url, :min_zoom, :max_zoom,
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
                "legend_url": layer["legend_url"],
                "min_zoom": min_zoom,
                "max_zoom": max_zoom,
            },
        )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM catalog_layers WHERE code = ANY(:codes)").bindparams(codes=[layer["code"] for layer in LAYERS])
    )
    op.execute(
        sa.text(
            "DELETE FROM layer_categories c WHERE c.code = ANY(:codes) AND NOT EXISTS (SELECT 1 FROM catalog_layers l WHERE l.category_id = c.id)"
        ).bindparams(codes=[code for code, *_ in CATEGORIES])
    )
