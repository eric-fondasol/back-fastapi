"""Couches SIGÉOM relayées par le back (signalement du 16/11/2026 : 403 en recette sur
« IDS_SGM_WMS/service.svc/get?SERVICE=WMS&REQUEST=GetMap… », aucun problème depuis localhost:4200).

Le WMS SIGÉOM de servicesvectoriels.atlas.gouv.qc.ca envoie « Access-Control-Allow-Origin: * » (d'où son
maintien en accès direct par la 0036), mais refuse en 403 toute requête dont l'en-tête Origin n'est pas
localhost : 200 sans Origin ou avec « Origin: http://localhost:4200 », 403 avec « Origin: https://example.com »
(vérifié le 16/11/2026). Mapbox charge les tuiles par fetch, le navigateur ajoute toujours Origin : depuis le
domaine de la recette, toutes les tuiles sont refusées. Les autres services du Canada demandés par le
navigateur (CPTAQ, Cadastre allégé, BDTQ) répondent 200 avec un Origin quelconque.

params.relayed = true : le navigateur demande les tuiles au back (GET /layer-catalog/{code}/tiles/{z}/{x}/{y}),
qui fait le GetMap (WMS 1.1.1, SRS) sans en-tête Origin. Les légendes (GetLegendGraphic) restent demandées
par le navigateur : une balise <img> sans crossorigin n'envoie pas Origin.

Retour arrière : relayed est retiré, les couches redeviennent des WMS demandés par le navigateur.
"""

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

SIGEOM_URL = "https://servicesvectoriels.atlas.gouv.qc.ca/IDS_SGM_WMS/service.svc/get"

CODES = [
    "ca-qc-mrnf-geologie-regionale",
    "ca-qc-mrnf-zones-morpho-sedimentologiques",
    "ca-qc-mrnf-zones-morpho-sedimentologiques-generales",
    "ca-qc-mrnf-provinces-geologiques",
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
        {"codes": CODES, "url": SIGEOM_URL},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE catalog_layers SET params = params - 'relayed', updated_at = now() WHERE code = ANY(:codes)"),
        {"codes": CODES},
    )
