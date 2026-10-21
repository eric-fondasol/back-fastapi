# Objets métier des enquêtes enregistrées et de leurs versions (ADR-0032 du front).
# Une enquête (table saved_pages) a des versions numérotées 1, 2, 3… (saved_page_versions) ; seule
# la dernière peut être écrasée. saved_pages.data reprend toujours le contenu de la dernière version.
# Règles et messages repris du back Symfony (InvestigationContent, SavedPage, InvestigationVersion).

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.errors import Conflict, InvalidRequest

MAX_NAME = 255
MAX_PROJECT_REF = 100
MAX_COMMENT = 2000
DEFAULT_SEARCH_LIMIT = 30


@dataclass(frozen=True)
class Investigation:
    id: int
    uuid: str
    project_ref: str | None
    name: str | None
    data: str

    # L'enquête a-t-elle une position ? Lue dans le contenu enregistré (« coordinates » non nul).
    @property
    def has_coordinates(self) -> bool:
        return has_coordinates(self.data)


# L'auteur d'une version : son profil (vidé si le compte est supprimé) et son nom, copié.
@dataclass(frozen=True)
class Author:
    user_id: str | None
    name: str | None


@dataclass(frozen=True)
class Version:
    id: str
    number: int
    comment: str | None
    author: Author
    created_at: datetime | None
    updated_at: datetime | None
    data: str | None = None


# Résultat de la recherche par numéro d'affaire ou par nom.
@dataclass(frozen=True)
class Summary:
    uuid: str
    project_ref: str | None
    name: str | None
    has_coordinates: bool


def has_coordinates(data: str | None) -> bool:
    try:
        decoded = json.loads(data or "")
    except ValueError:
        return False

    return isinstance(decoded, dict) and decoded.get("coordinates") is not None


def content(data: str) -> str:
    if not data.strip():
        raise InvalidRequest("Le contenu de l'enquete (data) est requis.")

    return data


def project_ref(value: str) -> str:
    trimmed = value.strip()

    if not trimmed or len(trimmed) > MAX_PROJECT_REF:
        raise InvalidRequest(f"Le n° de projet ou de devis est requis ({MAX_PROJECT_REF} caracteres au plus).")

    return trimmed


def name(value: str | None) -> str | None:
    return _optional(value, MAX_NAME, "Le nom de l'enquete")


def comment(value: str | None) -> str | None:
    return _optional(value, MAX_COMMENT, "Le commentaire")


def _optional(value: str | None, maximum: int, label: str) -> str | None:
    trimmed = (value or "").strip()

    if len(trimmed) > maximum:
        raise InvalidRequest(f"{label} depasse {maximum} caracteres.")

    return trimmed or None


# Seule la dernière version s'écrase ; une version inexistante est signalée par l'appelant (404).
def assert_revisable(requested: int, latest: int) -> None:
    if requested != latest:
        raise Conflict(
            f"Seule la derniere version (V{latest}) peut etre ecrasee, pas la V{requested} : enregistrer une nouvelle version."
        )


# Champ texte d'un corps JSON. « data » peut aussi arriver en objet ou en liste : il est alors
# enregistré sous forme de texte JSON.
def text_field(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)

    if value is None or isinstance(value, str):
        return value

    if isinstance(value, dict | list) and key == "data":
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    raise InvalidRequest(f"Le champ {key} doit etre une chaine.")
