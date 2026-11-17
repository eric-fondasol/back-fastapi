# Données du service externe : les sites et les sondages de la carte, lus sur l'API Solscore v2
# (routes /general/…) par le client partagé app/core/solscore_api.py.

from app.core import solscore_api
from app.core.solscore_api import SolscoreApiUnavailable
from app.domains.map.schemas import Bounds

__all__ = ["SolscoreApiUnavailable", "area_features"]


# Points GeoJSON (« features ») renvoyés par une route /general/… de l'API Solscore pour cette emprise.
# « flags » : valeurs exigées des indicateurs du sondage (has_lithology: True…), toutes à la fois ;
# en vue Sites, l'API garde les sites qui ont au moins un sondage les respectant toutes.
def area_features(route: str, bounds: Bounds, flags: dict[str, bool] | None = None) -> list[dict]:
    body = solscore_api.post(route, {"bounds": bounds.model_dump(), **(flags or {})})

    if not isinstance(body, dict) or not isinstance(body.get("features"), list):
        raise SolscoreApiUnavailable(str(body)[:200])
    return body["features"]
