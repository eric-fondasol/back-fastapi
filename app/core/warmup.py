# Préchauffage au démarrage : prépare ce que la première requête devrait sinon attendre
# (environ 200 ms pour les clés Azure et 300 ms par connexion à la base).

import time
from collections.abc import Callable

from sqlalchemy import text

from app.core import auth
from app.core.logger import logger
from app.database.connection import apisolscore_engine, refonte_engine


# Appelé une fois au démarrage, depuis lifespan dans main.py.
def warm_up() -> None:
    # Télécharge les clés de signature Azure et les met en cache dans auth.jwks_client().
    _step("azure signing keys", lambda: auth.jwks_client().get_signing_keys())
    _step("apisolscore connections", _open_connections)
    _step("refonte connection", _open_refonte_connection)


# Ouvre deux connexions en même temps, car le front interroge sites et sondages en parallèle.
# À la sortie du « with », elles retournent dans le pool, ouvertes et prêtes à resservir.
def _open_connections() -> None:
    with apisolscore_engine.connect() as first, apisolscore_engine.connect() as second:
        for connection in (first, second):
            connection.execute(text("SELECT 1"))


# Une connexion à la base métier suffit : ses routes ne sont pas appelées en parallèle au chargement.
def _open_refonte_connection() -> None:
    with refonte_engine.connect() as connection:
        connection.execute(text("SELECT 1"))


# Exécute une étape et journalise sa durée. Un échec n'empêche pas l'API de démarrer :
# il est journalisé et la première requête refera l'opération.
def _step(name: str, step: Callable[[], object]) -> None:
    started = time.perf_counter()

    try:
        step()
    except Exception:
        logger.warning("warm-up: %s failed, the first request will retry", name, exc_info=True)
        return

    logger.info("warm-up: %s ready in %d ms", name, (time.perf_counter() - started) * 1000)
