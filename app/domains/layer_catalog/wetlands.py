# Import des milieux humides du sud du Québec (table quebec_wetlands, migration 0049, ADR-0069 du front) depuis
# mh_2023.gpkg, lancé à la main sur le serveur de l'API ; procédure dans docs/couches/couches-en-base.md.
#
#   python -m app.domains.layer_catalog.wetlands <mh_2023.gpkg>
#
# Le chargement est commun avec les milieux humides potentiels (polygon_layers.py).

import sys

from app.domains.layer_catalog.polygon_layers import PolygonLayer, main

LAYER = PolygonLayer(
    table="quebec_wetlands",
    source_table="milieux_humides_sudqc_nov2023",
    key="globalid",
    srid=4326,
    class_column="classe",
    class_table="quebec_wetland_classes",
    label="Milieux humides",
)

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], LAYER, "python -m app.domains.layer_catalog.wetlands"))
