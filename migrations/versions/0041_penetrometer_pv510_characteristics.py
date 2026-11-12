"""Caractéristiques du pénétromètre selon le PV-510 (12/11/2026) : masse de la pointe et enfoncement de mesure sur
l'essai ; masse de la pointe, section de pointe et enfoncement sur le type de machine. Qd se calcule par
qd = N·M²·H / (e·(M + pointe + accessoires + ⌊z + 1⌋·tige)·S·g), comme dans le classeur PV-510.

`anvil_mass` garde son nom mais vaut désormais la masse des accessoires (enclume, tête de battage et porte-pointe),
d'après la tâche « Éditer les données » ; `rod_mass` est une masse par mètre de tige.

Retour arrière : les colonnes ajoutées sont retirées, avec leurs valeurs.
"""

from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE penetrometer_tests ADD COLUMN tip_mass float8, ADD COLUMN penetration float8")
    op.execute("ALTER TABLE penetrometer_machine_types ADD COLUMN tip_mass float8, ADD COLUMN tip_section float8, ADD COLUMN penetration float8")


def downgrade() -> None:
    op.execute("ALTER TABLE penetrometer_machine_types DROP COLUMN tip_mass, DROP COLUMN tip_section, DROP COLUMN penetration")
    op.execute("ALTER TABLE penetrometer_tests DROP COLUMN tip_mass, DROP COLUMN penetration")
