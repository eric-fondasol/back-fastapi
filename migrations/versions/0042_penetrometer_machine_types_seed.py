"""Types de pénétromètre de `penetrometres.csv` (tâche « Éditer les données », 12/11/2026), mêmes valeurs que le
classeur PV-510. Hauteur de chute convertie de cm en m ; masse des accessoires = enclume + tête de battage +
porte-pointe ; masse des tiges par mètre ; le diamètre des tiges, absent de la formule de Qd, n'est pas repris.
« autre » n'est pas un type : c'est la saisie libre du front.

Un type déjà présent sous le même nom reprend les valeurs du fichier.

Retour arrière : les cinq types sont retirés, sauf ceux qu'un essai utilise (clé étrangère RESTRICT).
"""

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

CM_TO_M = 0.01

PENETROMETRES_CSV = (
    ("DPL FONDASOL", 50, 10, 2.64, 0.23, 10, 4.41, 0, 0.21, 10),
    ("DPH strasbourg", 50, 50, 5.62, 0.61, 20, 13, 0.89, 1.28, 10),
    ("DPSHB TECOINSA", 75, 63.5, 5.62, 0.61, 20, 13, 0.89, 1.28, 10),
    ("DPSHB SOCO/SMRI", 75, 63.5, 5.62, 0.61, 20, 9.9, 0.89, 1.28, 10),
    ("DPSHB SOCO 10", 75, 63.5, 5.62, 0.61, 20, 8.76, 0.89, 1.54, 10),
)


def machine_types() -> list[dict[str, float | str]]:
    return [
        {
            "type": name,
            "hammer_drop_height": round(drop_height_cm * CM_TO_M, 4),
            "hammer_mass": hammer_mass,
            "rod_mass": rod_mass,
            "tip_mass": tip_mass,
            "tip_section": tip_section,
            "anvil_mass": round(anvil + driving_head + cone_holder, 4),
            "penetration": penetration,
        }
        for name, drop_height_cm, hammer_mass, rod_mass, tip_mass, tip_section, anvil, driving_head, cone_holder, penetration in PENETROMETRES_CSV
    ]


def seed(connection: Connection) -> None:
    connection.execute(
        text(
            "INSERT INTO penetrometer_machine_types (type, hammer_drop_height, hammer_mass, rod_mass, tip_mass, tip_section, anvil_mass, penetration) "
            "VALUES (:type, :hammer_drop_height, :hammer_mass, :rod_mass, :tip_mass, :tip_section, :anvil_mass, :penetration) "
            "ON CONFLICT (type) DO UPDATE SET hammer_drop_height = EXCLUDED.hammer_drop_height, hammer_mass = EXCLUDED.hammer_mass, "
            "rod_mass = EXCLUDED.rod_mass, tip_mass = EXCLUDED.tip_mass, tip_section = EXCLUDED.tip_section, "
            "anvil_mass = EXCLUDED.anvil_mass, penetration = EXCLUDED.penetration"
        ),
        machine_types(),
    )


def upgrade() -> None:
    seed(op.get_bind())


def downgrade() -> None:
    op.get_bind().execute(
        text(
            "DELETE FROM penetrometer_machine_types m WHERE m.type = ANY(:types) "
            "AND NOT EXISTS (SELECT 1 FROM penetrometer_tests t WHERE t.machine_type_id = m.id)"
        ),
        {"types": [row[0] for row in PENETROMETRES_CSV]},
    )
