# Objets métier du cadastre, manipulés par services.py. Ce ne sont pas des modèles de tables.

from dataclasses import dataclass


# Référence cadastrale d'une parcelle, telle que demandée par le front (déjà normalisée par schemas.py).
@dataclass(frozen=True)
class ParcelReference:
    # Code INSEE de la commune (5 caractères, ex. 84129 ou 2A004 en Corse).
    insee_code: str
    # Section cadastrale sur 2 caractères (ex. AB, 0A).
    section: str
    # Numéro de parcelle sur 4 chiffres (ex. 0004).
    number: str
    # Code de l'ancienne commune absorbée, sur 3 chiffres ; « 000 » s'il n'y en a pas.
    absorbed_commune: str

    # Identifiant unique de parcelle (IDU, 14 caractères) : INSEE + commune absorbée + section + numéro.
    @property
    def idu(self) -> str:
        return f"{self.insee_code}{self.absorbed_commune}{self.section}{self.number}"


# Parcelle trouvée dans le cadastre de l'IGN.
@dataclass(frozen=True)
class Parcel:
    idu: str
    insee_code: str
    commune_name: str
    absorbed_commune: str
    section: str
    number: str
    # Numéro de feuille du plan cadastral, s'il est connu.
    sheet: int | None
    # Contenance : surface officielle inscrite au cadastre, en m², si elle est connue.
    official_area_m2: int | None
    # Surface calculée à partir du contour (services.geodesic_area_m2), en m².
    computed_area_m2: float
    # Contour de la parcelle en GeoJSON (Polygon ou MultiPolygon, coordonnées longitude/latitude).
    geometry: dict
