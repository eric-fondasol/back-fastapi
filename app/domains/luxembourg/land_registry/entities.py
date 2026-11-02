# Objets métier du cadastre du Luxembourg, manipulés par services.py. Ce ne sont pas des modèles de tables.

from dataclasses import dataclass


# Section cadastrale et sa commune cadastrale (ex. section « F », « Ville Haute », commune « Luxembourg »).
@dataclass(frozen=True)
class Zoning:
    municipality: str | None
    section: str | None
    section_name: str | None


# Parcelle du plan cadastral numérisé (PCN), telle que publiée par le WFS INSPIRE du géoportail.
@dataclass(frozen=True)
class Parcel:
    # Référence cadastrale nationale, unique au Luxembourg (ex. « 075F00405002684 » : commune 075, section F).
    reference: str
    # Numéro de la parcelle, unique dans sa section seulement (ex. « 405/2684 »).
    number: str
    # Superficie officielle publiée par le cadastre, en m² (None si le service ne la donne pas).
    area_m2: float | None
    # Contour de la parcelle en GeoJSON (Polygon ou MultiPolygon, coordonnées longitude/latitude).
    geometry: dict
    zoning: Zoning
