# Import des milieux humides potentiels du Québec (table quebec_potential_wetlands, migration 0050, ADR-0070 du
# front) depuis mh_potentiel_2023.gpkg, lancé à la main sur le serveur de l'API ; procédure dans
# docs/couches/couches-en-base.md. Le fichier est en NAD83 / Québec Lambert (EPSG:32198) ; 2,4 millions de
# polygones, de l'ordre de 6 Go en base.
#
#   python -m app.domains.layer_catalog.potential_wetlands <mh_potentiel_2023.gpkg>
#
# Le chargement est commun avec les milieux humides de la cartographie détaillée (polygon_layers.py).

import sys

from app.domains.layer_catalog.polygon_layers import PolygonLayer, main

LAYER = PolygonLayer(
    table="quebec_potential_wetlands",
    source_table="mh_potentiel_qc",
    key="objectid",
    srid=32198,
    class_column="classe",
    class_table="quebec_potential_wetland_classes",
    label="Milieux humides potentiels",
)

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], LAYER, "python -m app.domains.layer_catalog.potential_wetlands"))
