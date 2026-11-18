# Import des sites CASIAS (table casias_sites, migration 0048, ADR-0068 du front) depuis l'extrait CASIAS.gpkg,
# lancé à la main dans le conteneur de l'API ; procédure dans docs/couches/couches-en-base.md.
#
#   python -m app.domains.layer_catalog.casias <CASIAS.gpkg>
#
# Le fichier a deux tables, les points (SSP_ETS_GE_POINT) et les emprises (SSP_ETS_GE_POLYGON), qui vont dans la
# même table avec leur forme (shape). Le chargement est commun avec les sites BASOL (site_layers.py).

import sys
from pathlib import Path

from sqlalchemy import Connection

from app.domains.layer_catalog import site_layers
from app.domains.layer_catalog.site_layers import MAX_MERCATOR_LATITUDE, ImportRefused, ImportResult, SiteLayer, SourceFile, wkb_of

__all__ = ["LAYER", "MAX_MERCATOR_LATITUDE", "ImportRefused", "ImportResult", "import_sites", "open_source", "table_columns", "wkb_of"]

LAYER = SiteLayer(table="casias_sites", shapes={"point": "SSP_ETS_GE_POINT", "polygon": "SSP_ETS_GE_POLYGON"}, label="Sites CASIAS")


def table_columns(connection: Connection) -> tuple[str, ...]:
    return site_layers.table_columns(connection, LAYER)


def open_source(path: Path, wanted: tuple[str, ...]) -> SourceFile:
    return site_layers.open_source(path, wanted, LAYER)


def import_sites(connection: Connection, source: SourceFile) -> ImportResult:
    return site_layers.import_sites(connection, source, LAYER)


if __name__ == "__main__":
    sys.exit(site_layers.main(sys.argv[1:], LAYER, "python -m app.domains.layer_catalog.casias"))
