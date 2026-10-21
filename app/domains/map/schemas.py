# Contrat de l'API du domaine map : forme et contrôles des requêtes, forme des réponses (Pydantic).

from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator


# Emprise de la carte. Field(ge=…, le=…) borne chaque valeur aux coordonnées possibles ;
# hors bornes, FastAPI répond 422 en nommant le champ en cause.
class Bounds(BaseModel):
    minLng: float = Field(ge=-180, le=180)
    maxLng: float = Field(ge=-180, le=180)
    minLat: float = Field(ge=-90, le=90)
    maxLat: float = Field(ge=-90, le=90)

    # Contrôle exécuté après celui des champs : le minimum ne doit pas dépasser le maximum.
    @model_validator(mode="after")
    def minimums_before_maximums(self) -> "Bounds":
        if self.minLng > self.maxLng:
            raise ValueError("minLng must be less than or equal to maxLng")

        if self.minLat > self.maxLat:
            raise ValueError("minLat must be less than or equal to maxLat")

        return self


class Position(BaseModel):
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)


# Corps des requêtes de map.
class AreaSearch(BaseModel):
    bounds: Bounds
    # Acceptée pour compatibilité avec le front, mais pas utilisée aujourd'hui.
    position: Optional[Position] = None


# Description de la réponse GeoJSON, utilisée pour la documentation /docs.
class PointFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict
    properties: dict


class FeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[PointFeature]
