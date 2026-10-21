# Contrat de l'API du cadastre : forme et contrôles de la requête, forme de la réponse (Pydantic).

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.domains.france.land_registry.entities import ParcelReference


# Corps de la requête. Chaque champ est contrôlé par une expression régulière ; une valeur qui ne
# correspond pas donne un 422 avant tout appel à l'IGN. « examples » alimente la page /docs.
class ParcelSearch(BaseModel):
    # 5 chiffres, ou 2A/2B suivi de 3 chiffres pour la Corse.
    code_insee: str = Field(pattern=r"^(\d{5}|2[ABab]\d{3})$", examples=["84129"])
    # 1 ou 2 caractères alphanumériques.
    section: str = Field(pattern=r"^[0-9A-Za-z]{1,2}$", examples=["AB"])
    # 1 à 4 chiffres.
    parcelle: str = Field(pattern=r"^\d{1,4}$", examples=["0004"])
    # Commune absorbée, 1 à 3 chiffres ; « 000 » par défaut.
    com_abs: str = Field(default="000", pattern=r"^\d{1,3}$", examples=["000"])

    # Met le code INSEE (2a → 2A) et la section (ab → AB) en majuscules, comme dans le cadastre.
    @field_validator("code_insee", "section")
    @classmethod
    def uppercase(cls, value: str) -> str:
        return value.upper()

    # Convertit la requête en entité, en complétant par des zéros à gauche au format du cadastre :
    # section « A » → « 0A », parcelle « 4 » → « 0004 », com_abs « 0 » → « 000 ».
    def reference(self) -> ParcelReference:
        return ParcelReference(
            insee_code=self.code_insee,
            section=self.section.rjust(2, "0"),
            number=self.parcelle.rjust(4, "0"),
            absorbed_commune=self.com_abs.rjust(3, "0"),
        )


# Propriétés renvoyées pour une parcelle (noms en français, comme dans le cadastre).
class ParcelProperties(BaseModel):
    idu: str
    code_insee: str
    nom_com: str
    com_abs: str
    section: str
    numero: str
    feuille: int | None
    # Surface officielle du cadastre, en m².
    contenance: int | None
    # Surface calculée à partir du contour, en m².
    superficie_m2: float


# Réponse au format GeoJSON.
class ParcelFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict
    properties: ParcelProperties


class ParcelCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[ParcelFeature]
