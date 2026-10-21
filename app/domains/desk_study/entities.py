# Objets métier de l'enquête documentaire servie par l'ancien back : résultat d'une planche
# (données d'une source publique pour une position) et ressource externe autorisée (Infoterre).
# Repris de PlancheResult et ExternalResource du back Symfony.

from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import urlsplit

from app.core.errors import Forbidden

# Seules les fiches du BRGM peuvent être relayées : jamais une adresse interne (GED, base,
# métadonnées de l'hébergeur…), sans quoi l'API servirait de rebond.
INFOTERRE_HOSTS = ("infoterre.brgm.fr", "ficheinfoterre.brgm.fr")


class PlancheStatus(Enum):
    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class PlancheResult:
    planche: str
    status: PlancheStatus
    elapsed_seconds: float
    data: Any = None
    reason: str | None = None
    from_cache: bool = False

    @property
    def usable(self) -> bool:
        return self.status is PlancheStatus.OK

    # Les champs absents (données d'une planche en échec, raison d'une planche aboutie) sont omis.
    def to_json(self) -> dict[str, Any]:
        body = {
            "status": self.status.value,
            "data": self.data,
            "reason": self.reason,
            "elapsedMs": round(self.elapsed_seconds * 1000),
            "fromCache": self.from_cache,
        }
        return {name: value for name, value in body.items() if value is not None}


def ok(planche: str, data: Any, elapsed: float) -> PlancheResult:
    return PlancheResult(planche, PlancheStatus.OK, elapsed, data=data)


def degraded(planche: str, reason: str, elapsed: float) -> PlancheResult:
    return PlancheResult(planche, PlancheStatus.DEGRADED, elapsed, reason=reason)


def unavailable(planche: str, reason: str, elapsed: float) -> PlancheResult:
    return PlancheResult(planche, PlancheStatus.UNAVAILABLE, elapsed, reason=reason)


def trusted_infoterre_url(url: str) -> str:
    parts = urlsplit(url)

    if not parts.scheme or not parts.hostname:
        raise Forbidden("URL externe illisible.")

    if parts.scheme.lower() not in ("http", "https"):
        raise Forbidden(f"Schema non autorise : {parts.scheme}.")

    if parts.hostname.lower() not in INFOTERRE_HOSTS:
        raise Forbidden(f"Hote non autorise : {parts.hostname.lower()}.")

    return url


# Coordonnée écrite dans une URL comme le faisait PHP : « 2 » plutôt que « 2.0 ».
def coordinate_text(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))
