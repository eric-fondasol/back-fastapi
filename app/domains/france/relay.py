# Réponse d'une route d'enquête de la France relayée vers l'API Solscore v2 : la réponse JSON de
# l'API telle quelle, ou un 502 quand l'API est injoignable ou en erreur (ce n'est pas la demande
# qui est en défaut).

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from app.core.logger import logger
from app.core.solscore_api import SolscoreApiUnavailable


def relayed(read: Callable[[], Any]) -> Any:
    try:
        answer = read()
    except SolscoreApiUnavailable as error:
        logger.warning("API Solscore indisponible : %s", error)
        raise HTTPException(status_code=502, detail="API Solscore injoignable") from error
    if not isinstance(answer, dict):
        logger.warning("Réponse inattendue de l'API Solscore : %s", str(answer)[:200])
        raise HTTPException(status_code=502, detail="Réponse inattendue de l'API Solscore")
    return answer
