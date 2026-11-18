# Import des sites BASOL (pollution des sols appelant une action des pouvoirs publics, table basol_sites, migration
# 0051, ADR-0071 du front) depuis l'extrait BASOL.gpkg, lancé à la main sur le serveur de l'API ; procédure dans
# docs/couches/couches-en-base.md.
#
#   python -m app.domains.layer_catalog.basol <BASOL.gpkg>
#
# Le fichier a deux tables, les points (SSP_INSTR_GE_POINT) et les emprises (SSP_INSTR_GE_POLYGONE), qui vont dans
# la même table avec leur forme (shape). Le chargement est commun avec les sites CASIAS (site_layers.py).

import sys

from app.domains.layer_catalog.site_layers import SiteLayer, main

LAYER = SiteLayer(table="basol_sites", shapes={"point": "SSP_INSTR_GE_POINT", "polygon": "SSP_INSTR_GE_POLYGONE"}, label="Sites BASOL")

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], LAYER, "python -m app.domains.layer_catalog.basol"))
