"""SCAN 25 de l'IGN au catalogue (topographie), écarté par la 0008 : il n'est servi que par l'URL
privée de la Géoplateforme, avec une clé d'API (ADR-0046 du front).

params.relayed = true : le navigateur ne demande pas les tuiles au service mais au back
(GET /layer-catalog/{code}/tiles/{z}/{x}/{y}), qui ajoute la clé IGN_PRIVATE_API_KEY. La clé n'est
donc ni en base ni dans le catalogue renvoyé au front. Le front reprend aussi cette couche comme
fond de plan.

Jeu de tuiles PM_6_16, niveaux 6 à 16 : ceux des capacités du service, lues le 27/10/2026. La liste du
métier donnait PM_0_18 et un zoom maximal de 17, auxquels le service répond 400.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

SCAN25 = {
    "code": "fr-ign-scan25",
    "category": "topographie",
    "label_fr": "Carte TOPO 25 (SCAN 25)",
    "label_en": "TOPO 25 map (SCAN 25)",
    "description_fr": "Carte topographique IGN au 1/25 000.",
    "description_en": "IGN 1:25,000 topographic map.",
    "url": "https://data.geopf.fr/private/wmts",
    "params": {
        "layer": "GEOGRAPHICALGRIDSYSTEMS.MAPS.SCAN25TOUR",
        "style": "normal",
        "tileMatrixSet": "PM_6_16",
        "format": "image/jpeg",
        "relayed": True,
    },
    "attribution": "© IGN – Géoplateforme",
    "min_zoom": 6,
    "max_zoom": 16,
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
                 attribution, min_zoom, max_zoom, position)
            SELECT :code, c.id, 'fr', :label_fr, :label_en, :description_fr, :description_en, 'wmts', :url,
                   CAST(:params AS jsonb), :attribution, :min_zoom, :max_zoom,
                   (SELECT coalesce(max(l.position), 0) + 1 FROM catalog_layers l WHERE l.category_id = c.id)
            FROM layer_categories c WHERE c.code = :category
            ON CONFLICT (code) DO NOTHING
            """
        ),
        {**SCAN25, "params": json.dumps(SCAN25["params"])},
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM catalog_layers WHERE code = :code").bindparams(code=SCAN25["code"]))
