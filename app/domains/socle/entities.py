# Objets métier du socle : paramétrage, statistiques de visite, traces de recherche d'adresse,
# zones à accès restreint, images d'attente. Règles reprises du back Symfony (Setting,
# DepartmentAccessPolicy, AddressSearchTracing, WaitingImage, LocalImageStorage).

import re
from dataclasses import dataclass
from datetime import datetime

# Types d'image acceptés au dépôt, reconnus à leurs premiers octets (pas au nom ni au type
# annoncé par le navigateur) : un SVG, qui peut porter du script, est refusé.
IMAGE_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/gif": (b"GIF87a", b"GIF89a"),
}
IMAGE_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}


@dataclass(frozen=True)
class Setting:
    email: str
    message: str
    user_manual_url: str
    recorded_at: datetime


@dataclass(frozen=True)
class AccessLimitedZone:
    id: str
    description: str
    latitude: float
    longitude: float
    radius_kilometers: float


# Une agence (table services) : « full_access » l'autorise sur tout le territoire.
@dataclass(frozen=True)
class Agency:
    code: str
    label: str
    has_full_access: bool


@dataclass(frozen=True)
class AddressSearchTracing:
    agency_code: str | None
    agency_label: str | None
    department_code: str
    covering_codes: str | None
    covering_labels: str | None
    authorized: bool
    longitude: float
    latitude: float
    recorded_at: datetime
    id: int | None = None


@dataclass(frozen=True)
class WaitingImage:
    id: int
    path: str
    active: bool


# Un agent peut chercher une adresse dans un département si son agence le couvre, ou si elle a
# un accès général. Un agent inconnu de l'annuaire n'est pas habilité.
def allows(agency: Agency | None, covering_agency_codes: list[str]) -> bool:
    if agency is None:
        return False

    return agency.has_full_access or agency.code in covering_agency_codes


# Agences de rattachement d'un département, jointes par « | » comme dans l'ancien contrat.
def joined(values: list[str]) -> str | None:
    return "|".join(values) if values else None


def image_type(content: bytes) -> str | None:
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"

    return next(
        (mime for mime, signatures in IMAGE_SIGNATURES.items() if any(content.startswith(signature) for signature in signatures)),
        None,
    )


# Nom de fichier stocké : « <uuid>-<nom nettoyé>.<extension du type réel> ».
def stored_name(prefix: str, original_name: str, mime: str) -> str:
    stem = original_name.rsplit(".", 1)[0] if "." in original_name else original_name
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-") or "image"
    return f"{prefix}-{slug}.{IMAGE_EXTENSIONS[mime]}"
