# Contrat de l'API des aléas naturels : forme des requêtes reçues (Pydantic). Les réponses sont
# celles de l'API Solscore v2, renvoyées telles quelles (voir docs/architecture.md, § 7).

from pydantic import Field

from app.domains.france.schemas import CommuneRadiusSearch

MAX_CAVITIES = 100


class CavitySearch(CommuneRadiusSearch):
    nb_cavites: int = Field(ge=0, le=MAX_CAVITIES, examples=[10])
