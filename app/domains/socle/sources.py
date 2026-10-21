# Le dossier des images d'attente (WAITING_IMAGES_DIR), monté dans le conteneur.
# Repris de LocalImageStorage du back Symfony : on ne lit et n'écrit qu'à plat dans ce dossier,
# le nom demandé est réduit à son dernier segment (pas de remontée d'arborescence).

from pathlib import Path

from app.core.config import config


def _directory() -> Path:
    return Path(config.waiting_images_dir)


def absolute_path(name: str) -> Path:
    return _directory() / Path(name).name


def store(name: str, content: bytes) -> None:
    _directory().mkdir(parents=True, exist_ok=True)
    absolute_path(name).write_bytes(content)


def delete(name: str) -> None:
    if name:
        absolute_path(name).unlink(missing_ok=True)
