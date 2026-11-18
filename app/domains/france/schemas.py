# Contrat commun aux routes d'enquête de la France relayées vers l'API Solscore v2 : le lieu
# recherché, un point et/ou des parcelles. Les noms des champs reprennent ceux de l'API Solscore
# (lat, lon, parcelles, code_insee, rayon_m), à qui le corps est transmis tel quel.

from typing import Annotated

from pydantic import BaseModel, Field, model_validator

# Bornes reprises du serveur du front : 50 parcelles de 3 à 5 000 sommets, rayon de 20 km au plus.
MAX_PARCELS = 50
MAX_PARCEL_VERTICES = 5000
MAX_RADIUS_METERS = 20000
MAX_BUFFER_METERS = 1000

Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]
Vertex = Annotated[list[float], Field(min_length=2, max_length=2)]
Outline = Annotated[list[Vertex], Field(min_length=3, max_length=MAX_PARCEL_VERTICES)]

INSEE_CODE_PATTERN = r"^(\d{5}|2[AB]\d{3})$"


class PlaceSearch(BaseModel):
    lat: Latitude | None = Field(default=None, examples=[45.7606])
    lon: Longitude | None = Field(default=None, examples=[4.859])
    parcelles: list[Outline] | None = Field(default=None, max_length=MAX_PARCELS)

    @model_validator(mode="after")
    def point_or_parcels(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat et lon vont ensemble")
        if self.lat is None and not self.parcelles:
            raise ValueError("un point (lat, lon) ou des parcelles sont attendus")
        return self

    def body(self) -> dict:
        return self.model_dump(exclude_none=True)


class CommuneSearch(PlaceSearch):
    code_insee: str | None = Field(default=None, pattern=INSEE_CODE_PATTERN, examples=["69383"])


class RadiusSearch(PlaceSearch):
    rayon_m: int = Field(ge=0, le=MAX_RADIUS_METERS, examples=[1000])


class CommuneRadiusSearch(CommuneSearch):
    rayon_m: int = Field(ge=0, le=MAX_RADIUS_METERS, examples=[1000])


class BufferSearch(PlaceSearch):
    rayon_m: int | None = Field(default=None, ge=1, le=MAX_BUFFER_METERS, examples=[20])
