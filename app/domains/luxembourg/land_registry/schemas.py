# Contrat de l'API du cadastre du Luxembourg : forme et contrôles de la requête, forme de la réponse (Pydantic).

from typing import Literal

from pydantic import BaseModel, Field


# Point cliqué ou survolé sur la carte, en WGS 84. Hors des bornes du globe : 422 avant tout appel au service.
class ParcelLocation(BaseModel):
    longitude: float = Field(ge=-180, le=180, examples=[6.1301])
    latitude: float = Field(ge=-90, le=90, examples=[49.6111])


class ParcelProperties(BaseModel):
    # Référence cadastrale nationale (« 075F00405002684 »), unique au Luxembourg.
    reference: str
    # Numéro de parcelle (« 405/2684 »), unique dans sa section seulement.
    number: str
    # Superficie officielle, en m².
    area_m2: float | None
    # Commune cadastrale (« Luxembourg »), section (« F ») et nom de la section (« Ville Haute »).
    municipality: str | None
    section: str | None
    section_name: str | None


# Réponse au format GeoJSON, comme les cadastres France et Québec.
class ParcelFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict
    properties: ParcelProperties


class ParcelCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[ParcelFeature]
