# Objets métier du cadastre du Québec, manipulés par services.py. Ce ne sont pas des modèles de tables.

from dataclasses import dataclass


# Lot du cadastre rénové du Québec, tel que publié par le « Cadastre allégé » (numéro et contour seulement).
@dataclass(frozen=True)
class Lot:
    # Numéro de lot, au format du cadastre : chiffres groupés par trois (ex. « 4 019 828 »).
    number: str
    # Contour du lot en GeoJSON (Polygon ou MultiPolygon, coordonnées longitude/latitude).
    geometry: dict
