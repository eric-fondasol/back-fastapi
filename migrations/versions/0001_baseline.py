"""Schéma de départ : celui de la base métier au 14/10/2026, repris du back Symfony.

Sur une base vide (tests, nouvel environnement), crée toutes les tables.
Sur une base déjà créée par Symfony, ne pas l'appliquer : « alembic stamp 0001 » la marque à jour.
Le SQL vient de pg_dump --schema-only (doctrine_migration_versions et spatial_ref_sys exclues).
"""

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # exec_driver_sql : le fichier est envoyé tel quel, en une fois (plusieurs instructions, des « :: »).
    op.get_bind().exec_driver_sql(Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    raise NotImplementedError("Le schéma de départ ne se défait pas.")
