# Journal de l'API : chaque ligne va dans logs/AAAA-MM-JJ.txt et dans la sortie de la console,
# préfixée de l'identifiant de la requête en cours.

import logging
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from app.core.config import config

# Identifiant de la requête en cours, posé par core/audit.py. « - » hors d'une requête (démarrage…).
request_id: ContextVar[str] = ContextVar("request_id", default="-")

# Le logger de l'application, à importer partout : « from app.core.logger import logger ».
logger = logging.getLogger("solscore")


class DailyFileHandler(logging.Handler):
    """Writes to <directory>/YYYY-MM-DD.txt and switches file when the day changes."""

    def __init__(self, directory: str):
        super().__init__()
        self.directory = Path(directory)
        # Crée le dossier des journaux s'il n'existe pas.
        self.directory.mkdir(parents=True, exist_ok=True)
        # Jour du fichier actuellement ouvert, et le fichier lui-même ; rien d'ouvert au départ.
        self.day: str | None = None
        self.stream = None

    # Appelé par logging pour chaque ligne à écrire.
    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Le jour est celui de la ligne, pas celui du démarrage de l'API.
            day = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d")

            # Changement de jour (ou première ligne) : ferme l'ancien fichier, ouvre celui du jour en ajout.
            if day != self.day:
                self._close_stream()
                self.stream = open(self.directory / f"{day}.txt", "a", encoding="utf-8")
                self.day = day

            self.stream.write(self.format(record) + "\n")
            # Écrit tout de suite sur le disque : la ligne est lisible même si l'API s'arrête brutalement.
            self.stream.flush()
        except Exception:
            # Une erreur d'écriture ne doit jamais faire échouer la requête : logging la signale sur stderr.
            self.handleError(record)

    def close(self) -> None:
        self._close_stream()
        super().close()

    def _close_stream(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
            self.day = None


# Filtre qui ajoute l'identifiant de la requête à chaque ligne, pour %(request_id)s dans le format.
# Renvoie True : la ligne est toujours conservée.
def _with_request_id(record: logging.LogRecord) -> bool:
    record.request_id = request_id.get()
    return True


def setup_logging() -> None:
    # Déjà configuré (module rechargé) : ne pas ajouter les handlers une seconde fois.
    if logger.handlers:
        return

    # Exemple : « 2026-10-11 14:03:12.457 INFO    [3f2a…] dev@fondasol.fr POST /searchSitesByArea -> 200 … »
    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d %(levelname)-7s [%(request_id)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Même format pour le fichier du jour et pour la console (visible avec docker compose logs).
    for handler in (DailyFileHandler(config.log_dir), logging.StreamHandler()):
        handler.setFormatter(formatter)
        handler.addFilter(_with_request_id)
        logger.addHandler(handler)

    logger.setLevel(logging.INFO)
    # N'envoie pas les lignes au logger racine, pour qu'elles n'apparaissent pas deux fois.
    logger.propagate = False


# Configuré dès le premier import du module.
setup_logging()
