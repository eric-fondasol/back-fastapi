from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.domains.france.land_registry.entities import ParcelReference


class ParcelSearch(BaseModel):
    code_insee: str = Field(pattern=r"^(\d{5}|2[ABab]\d{3})$", examples=["84129"])
    section: str = Field(pattern=r"^[0-9A-Za-z]{1,2}$", examples=["AB"])
    parcelle: str = Field(pattern=r"^\d{1,4}$", examples=["0004"])
    com_abs: str = Field(default="000", pattern=r"^\d{1,3}$", examples=["000"])

    @field_validator("code_insee", "section")
    @classmethod
    def uppercase(cls, value: str) -> str:
        return value.upper()

    def reference(self) -> ParcelReference:
        return ParcelReference(
            insee_code=self.code_insee,
            section=self.section.rjust(2, "0"),
            number=self.parcelle.rjust(4, "0"),
            absorbed_commune=self.com_abs.rjust(3, "0"),
        )


class ParcelProperties(BaseModel):
    idu: str
    code_insee: str
    nom_com: str
    com_abs: str
    section: str
    numero: str
    feuille: int | None
    contenance: int | None
    superficie_m2: float


class ParcelFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict
    properties: ParcelProperties


class ParcelCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[ParcelFeature]
