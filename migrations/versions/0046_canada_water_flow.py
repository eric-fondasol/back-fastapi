"""Sens d'écoulement des cours d'eau du Canada au catalogue (couche « Water flow » de Toporama, ligne ajoutée
par le métier le 17/11/2026 au fichier du catalogue).

Vérifié le 17/11/2026 autour de Montréal : la couche nhn:nhn:network:flowdirection_1 figure dans le
GetCapabilities du service hydro_network_en de GéoGratis (RNCan), GetMap et GetLegendGraphic répondent 200 en
image/png en WMS 1.3.0, avec « Access-Control-Allow-Origin: * » : les tuiles sont demandées directement par le
navigateur, sans relais (contrairement à Forêt ouverte, 0036, et au SIGÉOM, 0044).

Le service ne dessine la couche qu'en dessous du 1/175 000 (MaxScaleDenominator) : zoom 12 minimum, comme le
fichier, soit environ 1/100 000 à la latitude de Montréal.

Le code passe en minuscules à tirets (contrainte de la table) ; position après les couches déjà rangées dans
« Eau - surface ».

Retour arrière : la couche est retirée.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None

URL = "https://maps.geogratis.gc.ca/wms/hydro_network_en"
LAYER = "nhn:nhn:network:flowdirection_1"
VERSION = "1.3.0"

WATER_FLOW = {
    "code": "ca-nrcan-nhn-water-flow",
    "category": "eau-surface",
    "label_fr": "Sens d’écoulement (Water flow)",
    "label_en": "Water flow direction",
    "description_fr": (
        "Flèches indiquant le sens d’écoulement de l’eau vers l’aval sur le réseau hydrographique, couche « Water "
        "flow » de Toporama (Réseau hydro national – GéoBase, RNCan)."
    ),
    "description_en": (
        'Arrows showing downstream water flow direction on the hydrographic network, the Toporama "Water flow" '
        "layer (National Hydro Network – GeoBase, NRCan)."
    ),
    "url": URL,
    "params": {"layers": LAYER, "format": "image/png", "version": VERSION},
    "attribution": "© Gouvernement du Canada – RNCan (Réseau hydro national – GéoBase)",
    "legend_url": (
        f"{URL}?SERVICE=WMS&VERSION={VERSION}&REQUEST=GetLegendGraphic&FORMAT=image/png&LAYER={LAYER}&SLD_VERSION=1.1.0"
    ),
    "min_zoom": 12,
    "max_zoom": 19,
}


def upgrade() -> None:
    seed(op.get_bind())


# Séparée de upgrade pour que les tests, qui vident les tables, puissent la rejouer.
def seed(connection: sa.Connection) -> None:
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
        {**WATER_FLOW, "params": json.dumps(WATER_FLOW["params"])},
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM catalog_layers WHERE code = :code"), {"code": WATER_FLOW["code"]})
