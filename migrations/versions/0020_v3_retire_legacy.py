"""Basculement v3, étape 7 : retrait des tables de l'ancien Solscore et des tables d'attente.

services, email_services, service_departments et access_limited_zones sont remplacées par
business_units (droits de recherche à réécrire autour d'elles dans le socle avant d'appliquer cette
migration) ; statistique_visites (legacy) est retirée, address_search_tracings gardée.
v3_warehouse_projects, v3_warehouse_surveys et v3_project_ids ne servaient qu'au basculement.

Pas de retour arrière : restaurer le dump pris avant le basculement.
"""

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

RETIRED_TABLES = (
    "statistique_visites",
    "access_limited_zones",
    "service_departments",
    "email_services",
    "services",
    "v3_project_ids",
    "v3_warehouse_surveys",
    "v3_warehouse_projects",
)


def upgrade() -> None:
    for table in RETIRED_TABLES:
        op.execute(f"DROP TABLE {table}")


def downgrade() -> None:
    raise RuntimeError("Basculement v3 sans retour arrière : restaurer le dump pris avant la migration 0014.")
