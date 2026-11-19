# Import des installations classées pour la protection de l'environnement (ICPE, table icpe_sites, migration 0055,
# ADR-0075 du front) depuis l'extrait ICPE.gpkg, lancé à la main sur le serveur de l'API ; procédure dans
# docs/couches/couches-en-base.md.
#
#   python -m app.domains.layer_catalog.icpe <ICPE.gpkg>
#
# Le fichier n'a qu'une table, des points (INSTALLATIONS_CLASSEES_SIMPLIFIE_GE), sans code_metier : une
# installation est identifiée par son code AIOT. Le chargement est commun avec les autres couches de sites
# (site_layers.py).

import sys

from app.domains.layer_catalog.site_layers import SiteLayer, main

LAYER = SiteLayer(
    table="icpe_sites",
    shapes={"point": "INSTALLATIONS_CLASSEES_SIMPLIFIE_GE"},
    label="Installations classées (ICPE)",
    key="code_aiot",
)

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], LAYER, "python -m app.domains.layer_catalog.icpe"))
