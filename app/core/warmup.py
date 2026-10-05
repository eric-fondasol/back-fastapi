import time
from collections.abc import Callable

from sqlalchemy import text

from app.core import auth
from app.core.logger import logger
from app.database.connection import apisolscore_engine


def warm_up() -> None:
    _step("azure signing keys", lambda: auth.jwks_client().get_signing_keys())
    _step("apisolscore connections", _open_connections)


def _open_connections() -> None:
    with apisolscore_engine.connect() as first, apisolscore_engine.connect() as second:
        for connection in (first, second):
            connection.execute(text("SELECT 1"))


def _step(name: str, step: Callable[[], object]) -> None:
    started = time.perf_counter()

    try:
        step()
    except Exception:
        logger.warning("warm-up: %s failed, the first request will retry", name, exc_info=True)
        return

    logger.info("warm-up: %s ready in %d ms", name, (time.perf_counter() - started) * 1000)
