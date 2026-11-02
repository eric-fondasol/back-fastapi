"""Plan cadastral du Luxembourg servi par le WMS INSPIRE du géoportail à la place de la couche opendata
(demande du responsable du projet du 02/11/2026 : la couche `parcels` remplit les parcelles en gris ou
beige opaque et cache les noms de rues et les bâtiments du fond de plan).

Le WMS INSPIRE (`CP.CadastralParcel`, seul style `CP.CadastralParcel.Default`) dessine les contours en
trait noir et les numéros de parcelle sur fond transparent : 84 % de pixels transparents contre 23 %,
mesuré le 02/11/2026 sur la même emprise de Luxembourg-Ville. C'est aussi le service que le back
interroge pour la sélection des parcelles (ADR-0050 du front) : les contours coïncident.

Zoom minimal relevé de 13 à 15 : au zoom 13, une image de 512 px demande 2 s en ville pour un
enchevêtrement illisible ; 0,4 s au zoom 15 et 0,24 s au zoom 17. La sélection des parcelles suit ce
zoom minimal. Le code de la couche ne change pas : le front la reconnaît à ce code. Pas de légende : celle
du service n'est qu'un carré vide et un carré noir.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

CODE = "lu-act-parcelles-cadastrales"

INSPIRE = {
    "description_fr": (
        "Plan cadastral numérisé (PCN) : limites et numéros des parcelles cadastrales du Grand-Duché, "
        "service INSPIRE du géoportail."
    ),
    "description_en": (
        "Digitised cadastral map (PCN): cadastral parcel boundaries and numbers of the Grand Duchy, "
        "geoportal INSPIRE service."
    ),
    "url": "https://wms.inspire.geoportail.lu/geoserver/cp/wms",
    "params": {"layers": "CP.CadastralParcel", "format": "image/png", "version": "1.3.0"},
    "min_zoom": 15,
}

OPENDATA = {
    "description_fr": "Plan cadastral numérisé (PCN) : limites des parcelles cadastrales du Grand-Duché.",
    "description_en": "Digitised cadastral map (PCN): cadastral parcel boundaries of the Grand Duchy.",
    "url": "https://wmts1.geoportail.lu/opendata/service",
    "params": {"layers": "parcels", "format": "image/png", "version": "1.3.0"},
    "min_zoom": 13,
}

UPDATE = sa.text(
    """
    UPDATE catalog_layers
    SET description_fr = :description_fr, description_en = :description_en, url = :url,
        params = CAST(:params AS jsonb), min_zoom = :min_zoom, updated_at = now()
    WHERE code = :code
    """
)


def _apply(connection: sa.Connection, values: dict) -> None:
    connection.execute(UPDATE, {**values, "code": CODE, "params": json.dumps(values["params"])})


def upgrade() -> None:
    seed(op.get_bind())


# Séparée de upgrade pour pouvoir l'appliquer seule à une base restée sur une révision antérieure.
def seed(connection: sa.Connection) -> None:
    _apply(connection, INSPIRE)


def downgrade() -> None:
    _apply(op.get_bind(), OPENDATA)
