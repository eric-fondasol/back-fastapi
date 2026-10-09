from dataclasses import dataclass


@dataclass(frozen=True)
class ParcelReference:
    insee_code: str
    section: str
    number: str
    absorbed_commune: str

    @property
    def idu(self) -> str:
        return f"{self.insee_code}{self.absorbed_commune}{self.section}{self.number}"


@dataclass(frozen=True)
class Parcel:
    idu: str
    insee_code: str
    commune_name: str
    absorbed_commune: str
    section: str
    number: str
    sheet: int | None
    official_area_m2: int | None
    computed_area_m2: float
    geometry: dict
