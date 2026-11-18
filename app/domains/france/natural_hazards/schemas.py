# Contrat de l'API des aléas naturels : forme des requêtes reçues (Pydantic). Les réponses sont
# celles de l'API Solscore v2, renvoyées telles quelles (voir docs/architecture.md, § 7).

from pydantic import Field

from app.domains.france.schemas import CommuneRadiusSearch, PlaceSearch

MAX_CAVITIES = 100
# Tampon autour du lieu pour les PPR : l'API Solscore prend 20 m par défaut et refuse au-delà de 1 000 m.
MAX_RISK_PLAN_BUFFER_METERS = 1000


class CavitySearch(CommuneRadiusSearch):
    nb_cavites: int = Field(ge=0, le=MAX_CAVITIES, examples=[10])


class RiskPlanSearch(PlaceSearch):
    rayon_m: int | None = Field(default=None, ge=1, le=MAX_RISK_PLAN_BUFFER_METERS, examples=[20])
