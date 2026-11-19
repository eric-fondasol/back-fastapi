"""Sous-catégories « CASIAS » et « ex-BASOL » dans « Environnement » (demande du responsable du projet du
19/11/2026) : le panneau Couches du front montre chacune comme une section repliable sous « Environnement », qui
garde ses autres couches.

« CASIAS » reçoit les sites CASIAS en points et en polygones ; « ex-BASOL » reçoit les couches « Pollution suspectée
ou avérée - information de l'administration » (points et polygones), issues de l'ancienne base BASOL, renommées
« ex-BASOL (points) » et « ex-BASOL (polygones) ». Les couches CASIAS gardent leur nom ; toutes gardent leur ordre
entre elles. Le front affiche les couches propres à « Environnement » d'abord, puis ses sous-catégories
(`LayerCatalogList`).

Une catégorie ou une couche absente fait échouer la migration, comme la 0039 : un catalogue incomplet doit être
signalé, pas laissé en l'état sans erreur.

Retour arrière : les quatre couches reviennent dans « Environnement » et les couches ex-BASOL reprennent leur nom
d'avant, les deux sous-catégories sont supprimées.
"""

import sqlalchemy as sa
from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None

PARENT = "environnement"
SUBCATEGORIES = [
    {
        "code": "casias",
        "label_fr": "CASIAS",
        "label_en": "CASIAS",
        "offset": 0,
        "layers": ["fr-georisques-casias-points", "fr-georisques-casias-polygones"],
    },
    {
        "code": "ex-basol",
        "label_fr": "ex-BASOL",
        "label_en": "ex-BASOL",
        "offset": 1,
        "layers": ["fr-georisques-pollution-instruction-points", "fr-georisques-pollution-instruction-polygones"],
    },
]
MOVED_LAYERS = [code for subcategory in SUBCATEGORIES for code in subcategory["layers"]]
RENAMED_LAYERS = [
    {
        "code": "fr-georisques-pollution-instruction-points",
        "label_fr": "ex-BASOL (points)",
        "label_en": "ex-BASOL (points)",
        "previous_fr": "Pollution suspectée ou avérée - information de l'administration (points)",
        "previous_en": "Suspected or proven pollution - administration information (points)",
    },
    {
        "code": "fr-georisques-pollution-instruction-polygones",
        "label_fr": "ex-BASOL (polygones)",
        "label_en": "ex-BASOL (polygons)",
        "previous_fr": "Pollution suspectée ou avérée - information de l'administration (polygones)",
        "previous_en": "Suspected or proven pollution - administration information (polygons)",
    },
]
RENAME = "UPDATE catalog_layers SET label_fr = :label_fr, label_en = :label_en, updated_at = now() WHERE code = :code"


class IncompleteCatalog(Exception):
    pass


def upgrade() -> None:
    seed(op.get_bind())


# Séparée de upgrade pour que les tests, qui vident les tables, puissent la rejouer.
def seed(connection: sa.Connection) -> None:
    parent = connection.execute(sa.text("SELECT id FROM layer_categories WHERE code = :parent"), {"parent": PARENT}).scalar()
    found = connection.execute(
        sa.text("SELECT count(*) FROM catalog_layers WHERE code = ANY(:layers)"), {"layers": MOVED_LAYERS}
    ).scalar()
    if parent is None or found != len(MOVED_LAYERS):
        raise IncompleteCatalog(
            f"Catégorie {PARENT} et couches {', '.join(MOVED_LAYERS)} attendues dans le catalogue : catalogue incomplet"
        )
    for subcategory in SUBCATEGORIES:
        connection.execute(
            sa.text(
                """
                INSERT INTO layer_categories (code, label_fr, label_en, position, parent_id)
                SELECT :code, :label_fr, :label_en, position + :offset, id FROM layer_categories WHERE code = :parent
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {key: subcategory[key] for key in ("code", "label_fr", "label_en", "offset")} | {"parent": PARENT},
        )
        connection.execute(
            sa.text(
                """
                UPDATE catalog_layers
                SET category_id = (SELECT id FROM layer_categories WHERE code = :code), updated_at = now()
                WHERE code = ANY(:layers)
                """
            ),
            {"code": subcategory["code"], "layers": subcategory["layers"]},
        )
    for layer in RENAMED_LAYERS:
        connection.execute(sa.text(RENAME), {"code": layer["code"], "label_fr": layer["label_fr"], "label_en": layer["label_en"]})


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE catalog_layers
            SET category_id = (SELECT id FROM layer_categories WHERE code = :parent), updated_at = now()
            WHERE code = ANY(:layers)
            """
        ),
        {"parent": PARENT, "layers": MOVED_LAYERS},
    )
    for layer in RENAMED_LAYERS:
        connection.execute(sa.text(RENAME), {"code": layer["code"], "label_fr": layer["previous_fr"], "label_en": layer["previous_en"]})
    connection.execute(
        sa.text("DELETE FROM layer_categories WHERE code = ANY(:codes)"),
        {"codes": [subcategory["code"] for subcategory in SUBCATEGORIES]},
    )
