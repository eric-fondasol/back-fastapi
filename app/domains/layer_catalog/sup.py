# Import des servitudes d'utilité publique liées à la pollution des sols (SUP, table sup_sites, migration 0054,
# ADR-0074 du front) depuis l'extrait SUP.gpkg, lancé à la main sur le serveur de l'API ; procédure dans
# docs/couches/couches-en-base.md.
#
#   python -m app.domains.layer_catalog.sup <SUP.gpkg>
#
# Le fichier n'a qu'une table, les emprises (SSP_CLASSIF_SUP_GE). Le chargement est commun avec les sites CASIAS,
# BASOL et SIS (site_layers.py).

import sys

from app.domains.layer_catalog.site_layers import SiteLayer, main

LAYER = SiteLayer(table="sup_sites", shapes={"polygon": "SSP_CLASSIF_SUP_GE"}, label="Servitudes SUP")

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], LAYER, "python -m app.domains.layer_catalog.sup"))
