"""Index spatiaux directs sur sites.geometry et surveys.geometry (carte du front, 09/11/2026).

La carte lit les sites et les sondages d'une emprise sur la base de la refonte, par l'API Solscore v2
(ADR-0058 du front) : « geometry && ST_MakeEnvelope(…) ». Seuls existaient des index sur
geometry::geography (idx_sites_geography, idx_surveys_geography), que ce filtre n'utilise pas.

CONCURRENTLY : pas de verrou sur les écritures pendant la création, d'où le bloc hors transaction.
IF NOT EXISTS : les index ont été posés à la main sur la base locale avant cette migration.

Retour arrière : les deux index sont supprimés, les index geography restent.
"""

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sites_geometry ON public.sites USING gist (geometry)")
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_surveys_geometry ON public.surveys USING gist (geometry)")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_surveys_geometry")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_sites_geometry")
