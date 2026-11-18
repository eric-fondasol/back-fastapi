# Contrat de l'API de l'hydrogéologie : forme des requêtes reçues (Pydantic). Les réponses sont
# celles de l'API Solscore v2, renvoyées telles quelles (voir docs/architecture.md, § 7).

from pydantic import BaseModel, Field

from app.domains.france.schemas import RadiusSearch

MAX_BSS_WORKS = 100


class BssSearch(RadiusSearch):
    nb_bss: int = Field(ge=0, le=MAX_BSS_WORKS, examples=[10])


# Station ADES : code BSS (« 06987A0186/S »). Dates facultatives au format AAAA-MM-JJ ; sans elles,
# toute la chronique de la station.
class ChronicleSearch(BaseModel):
    code_bss: str = Field(pattern=r"^[0-9A-Za-z]{1,12}/[0-9A-Za-z._-]{1,30}$", examples=["06987A0186/S"])
    date_debut: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_fin: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    def body(self) -> dict:
        return self.model_dump(exclude_none=True)
