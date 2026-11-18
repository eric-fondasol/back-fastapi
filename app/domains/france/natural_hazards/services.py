# Logique métier des aléas naturels : appelé par routes.py, appelle sources.py.

from app.core.logger import logger
from app.core.solscore_api import SolscoreApiUnavailable
from app.domains.france.natural_hazards import sources


# Les six aléas réunis en un seul objet (alea_rga, alea_inondation…). Un aléa en échec est laissé de
# côté (et journalisé) ; si aucun ne répond, l'API est indisponible.
# Appels l'un après l'autre, dans l'ordre de HAZARD_ROUTES (les plus rapides d'abord) : l'API Solscore
# traite ses requêtes une à une ; lancés ensemble, les rapides attendaient derrière les zones
# inondables et dépassaient le délai de 30 s (constaté le 17/11/2026).
def natural_hazards(body: dict) -> dict:
    merged: dict = {}
    for name in sources.HAZARD_ROUTES:
        try:
            answer = sources.hazard(name, body)
        except SolscoreApiUnavailable as error:
            logger.warning("Aléa %s indisponible : %s", name, error)
            continue
        if isinstance(answer, dict):
            merged.update({key: value for key, value in answer.items() if key != "mode_recherche"})

    if not merged:
        raise SolscoreApiUnavailable("aucun aléa naturel n'a répondu")
    return merged
