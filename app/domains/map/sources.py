# Données du service externe : les sites et les sondages de la carte, lus sur l'API Solscore v2
# (routes /general/…), avec le jeton d'un compte de service obtenu par POST /auth.

import threading

import httpx

from app.core.config import config
from app.core.timing import timed
from app.domains.map.schemas import Bounds

# Au-delà de 30 s sans réponse (grande emprise), l'API Solscore est considérée comme injoignable.
TIMEOUT_SECONDS = 30.0

# Remplacé par les tests pour simuler l'API Solscore (httpx.MockTransport).
transport: httpx.BaseTransport | None = None

# Jeton du compte de service, gardé entre les requêtes et redemandé quand l'API répond 401
# (jeton expiré). Le verrou évite que plusieurs requêtes simultanées le redemandent en même temps.
_token: str | None = None
_token_lock = threading.Lock()


# Erreur propre au domaine, traduite en 502 par routes.py. Le service n'a pas à connaître httpx.
class SolscoreApiUnavailable(Exception):
    pass


# Points GeoJSON (« features ») renvoyés par une route /general/… de l'API Solscore pour cette emprise.
# « flags » : valeurs exigées des indicateurs du sondage (has_lithology: True…), toutes à la fois ;
# en vue Sites, l'API garde les sites qui ont au moins un sondage les respectant toutes.
def area_features(route: str, bounds: Bounds, flags: dict[str, bool] | None = None) -> list[dict]:
    if not (config.solscore_api_url and config.solscore_api_username and config.solscore_api_password):
        raise SolscoreApiUnavailable("SOLSCORE_API_URL, SOLSCORE_API_USERNAME ou SOLSCORE_API_PASSWORD absent de la configuration")

    try:
        # Durée enregistrée sous « solscore_api » dans l'audit.
        with timed("solscore_api"), httpx.Client(base_url=config.solscore_api_url.rstrip("/"), timeout=TIMEOUT_SECONDS, transport=transport) as client:
            search = {"bounds": bounds.model_dump(), **(flags or {})}
            response = _post(client, route, search, _current_token(client))
            if response.status_code == 401:
                response = _post(client, route, search, _renewed_token(client))
            response.raise_for_status()
            body = response.json()
    # Erreur réseau, délai dépassé, identifiants refusés, ou réponse qui n'est pas du JSON (ValueError).
    except (httpx.HTTPError, ValueError) as error:
        raise SolscoreApiUnavailable(f"{type(error).__name__}: {error}") from error

    if not isinstance(body, dict) or not isinstance(body.get("features"), list):
        raise SolscoreApiUnavailable(str(body)[:200])
    return body["features"]


def _post(client: httpx.Client, route: str, body: dict, token: str) -> httpx.Response:
    return client.post(route, json=body, headers={"Authorization": f"Bearer {token}"})


def _current_token(client: httpx.Client) -> str:
    with _token_lock:
        global _token
        if _token is None:
            _token = _login(client)
        return _token


def _renewed_token(client: httpx.Client) -> str:
    with _token_lock:
        global _token
        _token = _login(client)
        return _token


# Formulaire OAuth2 « password » attendu par POST /auth ; la réponse porte access_token.
def _login(client: httpx.Client) -> str:
    response = client.post(
        "/auth",
        data={"username": config.solscore_api_username, "password": config.solscore_api_password.get_secret_value()},
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError("réponse de /auth sans access_token")
    return token
