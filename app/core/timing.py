# Chronomètre les étapes d'une requête (auth, db, geojson…). Les durées sont ajoutées à l'audit
# dans details.timings_ms.

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

# Durées de la requête en cours, en millisecondes, par étape. ContextVar : chaque requête a son
# propre dictionnaire, même quand plusieurs requêtes sont traitées en même temps.
# Vaut None hors d'une requête auditée (démarrage, /api/health…) : rien n'est alors enregistré.
timings: ContextVar[dict[str, float] | None] = ContextVar("timings", default=None)


# Usage : « with timed("db"): ... » mesure la durée du bloc sous le nom « db ».
@contextmanager
def timed(step: str) -> Iterator[None]:
    started = time.perf_counter()

    try:
        yield
    # finally : la durée est enregistrée même si le bloc lève une erreur.
    finally:
        current = timings.get()

        if current is not None:
            # Additionne si l'étape est mesurée plusieurs fois dans la même requête.
            current[step] = current.get(step, 0) + (time.perf_counter() - started) * 1000
