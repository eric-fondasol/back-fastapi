# Import des établissements pollueurs (registre IREP, table polluting_facilities, migration 0053, ADR-0073 du
# front) depuis l'extrait ETABLISSEMENTS_POLLUEURS.gpkg, lancé à la main sur le serveur de l'API ; procédure dans
# docs/couches/couches-en-base.md.
#
#   python -m app.domains.layer_catalog.polluting_facilities <ETABLISSEMENTS_POLLUEURS.gpkg>
#
# Le fichier n'a qu'une table, des points (ETABLISSEMENTS_POLLUEURS), sans code_metier : un établissement est
# identifié par son identifiant IREP. Le chargement est commun avec les sites CASIAS, BASOL et SIS (site_layers.py).

import sys

from app.domains.layer_catalog.site_layers import SiteLayer, main

LAYER = SiteLayer(
    table="polluting_facilities",
    shapes={"point": "ETABLISSEMENTS_POLLUEURS"},
    label="Établissements pollueurs",
    key="identifiant",
)

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], LAYER, "python -m app.domains.layer_catalog.polluting_facilities"))
