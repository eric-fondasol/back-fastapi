from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator


class Bounds(BaseModel):
    minLng: float = Field(ge=-180, le=180)
    maxLng: float = Field(ge=-180, le=180)
    minLat: float = Field(ge=-90, le=90)
    maxLat: float = Field(ge=-90, le=90)

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


class AreaSearch(BaseModel):
    bounds: Bounds
    position: Optional[Position] = None


class PointFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict
    properties: dict


class FeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[PointFeature]
