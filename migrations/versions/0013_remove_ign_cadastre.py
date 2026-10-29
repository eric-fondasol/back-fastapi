"""Retrait du cadastre IGN (fr-cadastre, Parcellaire Express) : pour la France, seul le cadastre
interactif Etalab (fr-cadastre-etalab) est conservé.

Les versions d'enquête (et saved_pages.data, copie de la dernière) qui affichaient fr-cadastre passent sur fr-cadastre-etalab, pour garder un
cadastre à la réouverture ; les favoris et « Mes couches » perdent simplement la couche.

downgrade remet la couche au catalogue, mais pas les favoris, préférences et versions d'enquête
modifiés : rien ne distingue une couche Etalab remplacée d'une couche Etalab choisie.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

REMOVED = "fr-cadastre"
KEPT = "fr-cadastre-etalab"

IGN_CADASTRE = {
    "code": REMOVED,
    "category": "cadastre",
    "label_fr": "Cadastre (IGN)",
    "label_en": "Cadastre (IGN)",
    "description_fr": "Parcellaire Express (PCI) de l'IGN, Géoplateforme. Limites de communes dès le zoom 12, parcelles à partir du zoom 15.",
    "description_en": "IGN Parcellaire Express (PCI), Géoplateforme. Municipal boundaries from zoom 12, parcels from zoom 15.",
    "url": "https://data.geopf.fr/wmts",
    "params": {"layer": "CADASTRALPARCELS.PARCELLAIRE_EXPRESS", "style": "PCI vecteur", "tileMatrixSet": "PM_0_19"},
    "attribution": "© IGN",
    "legend_url": "https://data.geopf.fr/annexes/ressources/legendes/CADASTRALPARCELS.PARCELLAIRE_EXPRESS-legend.png",
    "min_zoom": 12,
    "max_zoom": 19,
}


def upgrade() -> None:
    remove(op.get_bind())


# Séparée de upgrade pour que les tests, qui vident les tables, puissent la rejouer.
def remove(connection: sa.Connection) -> None:
    connection.execute(sa.text("DELETE FROM catalog_layers WHERE code = :code"), {"code": REMOVED})
    connection.execute(sa.text("DELETE FROM user_favorite_layers WHERE layer_id = :code"), {"code": REMOVED})
    connection.execute(
        sa.text(
            """
            UPDATE user_preferences
            SET map_layers = (
                SELECT coalesce(jsonb_agg(layer ORDER BY position), '[]'::jsonb)
                FROM jsonb_array_elements(map_layers) WITH ORDINALITY AS kept(layer, position)
                WHERE layer->>'layer_id' IS DISTINCT FROM :code
            )
            WHERE map_layers @> CAST(:match AS jsonb)
            """
        ),
        {"code": REMOVED, "match": json.dumps([{"layer_id": REMOVED}])},
    )
    for table in ("saved_page_versions", "saved_pages"):
        connection.execute(
            sa.text(f"UPDATE {table} SET data = replace(data, :removed, :kept) WHERE strpos(data, :removed) > 0"),
            {"removed": json.dumps(REMOVED), "kept": json.dumps(KEPT)},
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO catalog_layers
                (code, category_id, country, label_fr, label_en, description_fr, description_en, kind, url, params,
                 attribution, legend_url, min_zoom, max_zoom, position)
            SELECT :code, c.id, 'fr', :label_fr, :label_en, :description_fr, :description_en, 'wmts', :url,
                   CAST(:params AS jsonb), :attribution, :legend_url, :min_zoom, :max_zoom,
                   (SELECT coalesce(max(l.position), 0) + 1 FROM catalog_layers l WHERE l.category_id = c.id)
            FROM layer_categories c WHERE c.code = :category
            ON CONFLICT (code) DO NOTHING
            """
        ).bindparams(**{**IGN_CADASTRE, "params": json.dumps(IGN_CADASTRE["params"])})
    )
