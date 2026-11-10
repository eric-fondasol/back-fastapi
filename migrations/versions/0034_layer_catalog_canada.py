"""Couches du Québec ajoutées au catalogue : lidar de Forêt ouverte, carte topographique 1/20 000 et
géologie du SIGÉOM (liste fournie par le métier le 10/11/2026, pour l'enquête documentaire du Canada).

Écarts avec la liste, vérifiés le 10/11/2026 par GetMap et GetLegendGraphic autour de Montréal :
- SIGÉOM (IDS_SGM_WMS) : la liste donnait la version 1.3.0, que le service refuse (« Value 1.3.0
  provided for a parameter version is invalid ») ; il répond en 1.1.1.
- Géologie du socle et zones morphosédimentologiques : sans légende, GetLegendGraphic ne renvoie qu'un
  carré de 28 × 18 px sans libellé.
- Provinces géologiques : absente de la liste, demandée par la carte « dépôts meubles et socle
  rocheux » de l'enquête ; couche SGM:Provinces_geologiques du même service, avec sa légende.
- Carte topographique 1/20 000 : sans légende dans la liste, et le service répond 400 à
  GetLegendGraphic.

Les codes passent en minuscules à tirets (contrainte de la table) ; position suit l'ordre de la liste,
après les couches déjà rangées dans la même catégorie.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None

FORET_OUVERTE_URL = "https://geoegl.msp.gouv.qc.ca/ws/mffpecofor.fcgi"
BDTQ_URL = "https://servicesmatriciels.mern.gouv.qc.ca/erdas-iws/ogc/wms/Cartes_Images"
SIGEOM_URL = "https://servicesvectoriels.atlas.gouv.qc.ca/IDS_SGM_WMS/service.svc/get"

FORET_OUVERTE = "© Gouvernement du Québec – MRNF (Forêt ouverte)"
BDTQ = "© Gouvernement du Québec – MRNF (BDTQ)"
SIGEOM = "© Gouvernement du Québec – MRNF (SIGÉOM)"


def wms(code, category, label, description, url, layer, attribution, zooms, version="1.3.0", legend=True):
    legend_url = (
        f"{url}?SERVICE=WMS&VERSION={version}&REQUEST=GetLegendGraphic&FORMAT=image/png&LAYER={layer}&SLD_VERSION=1.1.0"
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
        "params": {"layers": layer, "format": "image/png", "version": version},
        "attribution": attribution,
        "legend_url": legend_url,
        "min_zoom": min_zoom,
        "max_zoom": max_zoom,
    }


def contour_lines(interval, min_zoom):
    return wms(
        f"ca-qc-mrnf-courbes-niveau-lidar-{interval}m",
        "topographie",
        (f"Courbe de niveau {interval} m (LIDAR)", f"Contour lines {interval} m (LIDAR)"),
        (
            f"Courbes de niveau issues du lidar, équidistance {interval} m. Usage visuel recommandé, pas d’analyse "
            "quantitative (MRNF, Forêt ouverte).",
            f"Lidar-derived contour lines, {interval} m interval. Recommended for visual use only, not quantitative "
            "analysis (MRNF, Forêt ouverte).",
        ),
        FORET_OUVERTE_URL,
        f"courbes_niveau_{interval}m",
        FORET_OUVERTE,
        (min_zoom, 20),
        legend=False,
    )


def sigeom(code, label, description, layer, legend=False):
    return wms(code, "geologie", label, description, SIGEOM_URL, layer, SIGEOM, (5, 18), version="1.1.1", legend=legend)


LAYERS = [
    wms(
        "ca-qc-mrnf-lits-ecoulement-lidar",
        "eau-surface",
        ("Lit d’écoulement potentiel (LIDAR)", "Potential flow beds (LIDAR)"),
        (
            "Trajet que l’eau devrait emprunter selon la topographie lidar, avec nature du lit (permanent / "
            "intermittent). Couche préliminaire ne remplaçant pas la GRHQ (MRNF, Forêt ouverte).",
            "Path water is expected to follow based on lidar topography, with bed type (permanent / intermittent). "
            "Preliminary layer, does not replace the GRHQ (MRNF, Forêt ouverte).",
        ),
        FORET_OUVERTE_URL,
        "hydrolidar_lits",
        FORET_OUVERTE,
        (12, 19),
    ),
    wms(
        "ca-qc-mrnf-hydro-surfacique-lidar",
        "eau-surface",
        ("Hydrographie surfacique forestière (LIDAR)", "Forest surface hydrography (LIDAR)"),
        (
            "Plans d’eau surfaciques (lacs, rivières à deux rives) livrés avec les lits d’écoulement potentiels "
            "lidar. Ne remplace pas la GRHQ (MRNF, Forêt ouverte).",
            "Surface water bodies (lakes, two-bank rivers) delivered with the lidar potential flow beds. Does not "
            "replace the GRHQ (MRNF, Forêt ouverte).",
        ),
        FORET_OUVERTE_URL,
        "hydrolidar_surfac",
        FORET_OUVERTE,
        (12, 19),
    ),
    contour_lines(1, 16),
    contour_lines(5, 16),
    contour_lines(10, 13),
    wms(
        "ca-qc-mrnf-topo-20k",
        "topographie",
        ("Carte topographique 1/20 000 (BDTQ)", "Topographic map 1:20,000 (BDTQ)"),
        (
            "Cartes topographiques officielles du Québec au 1/20 000 (BDTQ), format matriciel avec estompage du "
            "relief. Plus mises à jour (MRNF).",
            "Québec's official 1:20,000 topographic maps (BDTQ), raster with hillshade. No longer updated (MRNF).",
        ),
        BDTQ_URL,
        "BDTQ-20K",
        BDTQ,
        (11, 17),
        legend=False,
    ),
    sigeom(
        "ca-qc-mrnf-geologie-regionale",
        ("Géologie du socle (régionale)", "Bedrock geology (regional)"),
        (
            "Carte géologique régionale du socle rocheux du Québec (SIGÉOM, MRNF). Affichage recommandé à 50 % "
            "d’opacité.",
            "Regional bedrock geology map of Québec (SIGÉOM, MRNF). Recommended display at 50% opacity.",
        ),
        "SGM:Geologie_regionale",
    ),
    sigeom(
        "ca-qc-mrnf-zones-morpho-sedimentologiques",
        ("Zones morphosédimentologiques", "Morpho-sedimentological zones"),
        (
            "Zones morphosédimentologiques : grands ensembles de dépôts de surface et de formes de terrain "
            "(SIGÉOM, MRNF). Affichage recommandé à 50 % d’opacité.",
            "Morpho-sedimentological zones: main groupings of surficial deposits and landforms (SIGÉOM, MRNF). "
            "Recommended display at 50% opacity.",
        ),
        "SGM:Zones_morpho_sedimentologiques",
    ),
    sigeom(
        "ca-qc-mrnf-zones-morpho-sedimentologiques-generales",
        ("Zones morphosédimentologiques générales", "General morpho-sedimentological zones"),
        (
            "Zones morphosédimentologiques généralisées à l’échelle du Québec (SIGÉOM, MRNF). Affichage recommandé "
            "à 50 % d’opacité.",
            "Morpho-sedimentological zones generalised at the scale of Québec (SIGÉOM, MRNF). Recommended display "
            "at 50% opacity.",
        ),
        "SGM:Zones_morpho_sedimentologiques_qc",
    ),
    sigeom(
        "ca-qc-mrnf-provinces-geologiques",
        ("Provinces géologiques", "Geological provinces"),
        (
            "Subdivisions géologiques du Québec : provinces et sous-provinces (SIGÉOM, MRNF). Affichage recommandé "
            "à 50 % d’opacité.",
            "Geological subdivisions of Québec: provinces and subprovinces (SIGÉOM, MRNF). Recommended display at "
            "50% opacity.",
        ),
        "SGM:Provinces_geologiques",
        legend=True,
    ),
]


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
                SELECT :code, c.id, 'ca', :label_fr, :label_en, :description_fr, :description_en, 'wms', :url,
                       CAST(:params AS jsonb), :attribution, :legend_url, :min_zoom, :max_zoom,
                       (SELECT coalesce(max(l.position), 0) + 1 FROM catalog_layers l WHERE l.category_id = c.id)
                FROM layer_categories c WHERE c.code = :category
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {**layer, "params": json.dumps(layer["params"])},
        )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM catalog_layers WHERE code = ANY(:codes)"),
        {"codes": [layer["code"] for layer in LAYERS]},
    )
