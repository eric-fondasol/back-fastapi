"""Couleurs plus distinctes pour les aires de protection des prélèvements d'eau potable (demande du responsable du
projet du 16/11/2026 : les zones imbriquées se distinguaient mal).

La 0038 reprenait les couleurs de l'API Solscore v2 : rouge, orange, magenta et violet, des teintes voisines qui,
superposées en transparence, se confondent (l'immédiate dans l'intermédiaire, elle-même dans l'éloignée). Les
nouvelles couleurs vont du plus restrictif au moins restrictif : rouge, orange, jaune, bleu pour les eaux
souterraines. Les eaux de surface n'ont que deux zones (immédiate et intermédiaire, 204 aires chacune dans la
base locale) : rouge et vert sarcelle. L'orange restait trop proche du rouge pour une zone dessinée sur l'autre,
et le bleu se confondait avec l'éloignée des eaux souterraines, souvent affichée à côté. Le front
dessine déjà les petites zones au-dessus des grandes (tri par surface).

Seules les couleurs changent : valeurs (Nom_AP) et libellés restent ceux de la 0038.

Retour arrière : les couleurs de la 0038.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None

GROUNDWATER = "ca-qc-aires-protection-eau-souterraine"
SURFACE_WATER = "ca-qc-aires-protection-eau-surface"

IMMEDIATE = "#d7191c"
BACTERIOLOGICAL = "#ff7f00"
VIROLOGICAL = "#ffd400"
REMOTE = "#1f78b4"
SURFACE_INTERMEDIATE = "#1b9e77"

COLORS = {
    GROUNDWATER: {"1": IMMEDIATE, "2": BACTERIOLOGICAL, "3": VIROLOGICAL, "4": REMOTE},
    SURFACE_WATER: {"1": IMMEDIATE, "2": SURFACE_INTERMEDIATE},
}

PREVIOUS_COLORS = {
    GROUNDWATER: {"1": "#e60000", "2": "#ff6b00", "3": "#ff00c5", "4": "#a900e6"},
    SURFACE_WATER: {"1": "#e60000", "2": "#ff6b00"},
}


def upgrade() -> None:
    recolor(op.get_bind(), COLORS)


def downgrade() -> None:
    recolor(op.get_bind(), PREVIOUS_COLORS)


# Séparée de upgrade pour que les tests, qui vident les tables, puissent la rejouer.
def recolor(connection: sa.Connection, colors: dict[str, dict[str, str]]) -> None:
    for code, by_value in colors.items():
        params = connection.execute(sa.text("SELECT params FROM catalog_layers WHERE code = :code"), {"code": code}).scalar()
        if params is None or "classes" not in params:
            continue
        classes = params["classes"]
        values = [{**entry, "color": by_value.get(str(entry.get("value")), entry.get("color"))} for entry in classes.get("values", [])]
        connection.execute(
            sa.text("UPDATE catalog_layers SET params = jsonb_set(params, '{classes,values}', CAST(:values AS jsonb)), updated_at = now() WHERE code = :code"),
            {"code": code, "values": json.dumps(values)},
        )
