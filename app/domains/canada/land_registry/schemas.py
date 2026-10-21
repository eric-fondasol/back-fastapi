# Contrat de l'API du cadastre du Québec : forme et contrôles de la requête, forme de la réponse (Pydantic).

from typing import Literal

from pydantic import BaseModel, Field


# Corps de la requête : le numéro de lot, avec ou sans espaces (« 4019828 » ou « 4 019 828 »).
# Une valeur qui ne contient pas que des chiffres et des espaces donne un 422 avant tout appel au service.
class LotSearch(BaseModel):
    lot: str = Field(pattern=r"^[\d ]{1,20}$", examples=["4 019 828"])

    # Numéro au format du cadastre : chiffres groupés par trois depuis la droite (« 4019828 » → « 4 019 828 »).
    def number(self) -> str:
        digits = self.lot.replace(" ", "").lstrip("0") or "0"
        groups = []
        while digits:
            groups.insert(0, digits[-3:])
            digits = digits[:-3]
        return " ".join(groups)


class LotProperties(BaseModel):
    no_lot: str


# Réponse au format GeoJSON, comme le cadastre France.
class LotFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict
    properties: LotProperties


class LotCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[LotFeature]
