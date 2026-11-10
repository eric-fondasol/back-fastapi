"""Couches lidar de Forêt ouverte relayées par le back (signalement du 10/11/2026 sur l'enquête Canada :
« Failed to fetch https://geoegl.msp.gouv.qc.ca/ws/mffpecofor.fcgi?… »).

Le service WMS de Forêt ouverte répond bien, mais sans en-tête Access-Control-Allow-Origin : Mapbox, qui
charge les tuiles par fetch, se les voit refuser par le navigateur. Les deux autres services du Québec
ajoutés par la 0034 (BDTQ, SIGÉOM) envoient « Access-Control-Allow-Origin: * » et restent demandés
directement.

params.relayed = true : le navigateur demande les tuiles au back
(GET /layer-catalog/{code}/tiles/{z}/{x}/{y}), qui fait le GetMap sur l'emprise de la tuile. Aucune clé :
contrairement au SCAN 25 (0010), ces couches restent au catalogue sans IGN_PRIVATE_API_KEY.

Retour arrière : relayed est retiré, les couches redeviennent des WMS demandés par le navigateur.
"""

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

FORET_OUVERTE_URL = "https://geoegl.msp.gouv.qc.ca/ws/mffpecofor.fcgi"

CODES = [
    "ca-qc-mrnf-lits-ecoulement-lidar",
    "ca-qc-mrnf-hydro-surfacique-lidar",
    "ca-qc-mrnf-courbes-niveau-lidar-1m",
    "ca-qc-mrnf-courbes-niveau-lidar-5m",
    "ca-qc-mrnf-courbes-niveau-lidar-10m",
]


def upgrade() -> None:
    relay(op.get_bind())


# Séparée de upgrade pour que les tests, qui vident les tables, puissent la rejouer.
def relay(connection: sa.Connection) -> None:
    connection.execute(
        sa.text(
            """
            UPDATE catalog_layers
            SET params = params || '{"relayed": true}'::jsonb, updated_at = now()
            WHERE code = ANY(:codes) AND kind = 'wms' AND url = :url
            """
        ),
        {"codes": CODES, "url": FORET_OUVERTE_URL},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE catalog_layers SET params = params - 'relayed', updated_at = now() WHERE code = ANY(:codes)"),
        {"codes": CODES},
    )
