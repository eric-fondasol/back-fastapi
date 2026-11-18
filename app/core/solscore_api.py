# Client de l'API Solscore v2 (solscore_apis) : POST d'un corps JSON sur une route, avec le jeton
# d'un compte de service obtenu par POST /auth. Partagé par les domaines qui lisent cette API
# (sites et sondages de la carte, données d'enquête de la France…).

import threading
from typing import Any

import httpx

from app.core.config import config
from app.core.timing import timed

# Au-delà de 30 s sans réponse, l'API Solscore est considérée comme injoignable. Certaines routes
# d'enquête (zones inondables) mettent plus de 10 s à répondre.
TIMEOUT_SECONDS = 30.0

# Remplacé par les tests pour simuler l'API Solscore (httpx.MockTransport).
transport: httpx.BaseTransport | None = None

# Jeton du compte de service, gardé entre les requêtes et redemandé quand l'API répond 401
# (jeton expiré). Le verrou évite que plusieurs requêtes simultanées le redemandent en même temps.
_token: str | None = None
_token_lock = threading.Lock()


# Erreur levée pour toute panne de l'API Solscore (configuration absente, réseau, statut d'erreur,
# réponse qui n'est pas du JSON). Les routes la traduisent en 502 : les domaines n'ont pas à
# connaître httpx.
class SolscoreApiUnavailable(Exception):
    pass


def configured() -> bool:
    return bool(config.solscore_api_url and config.solscore_api_username and config.solscore_api_password)


# Envoie « body » en JSON sur « route » et renvoie la réponse JSON décodée.
def post(route: str, body: dict) -> Any:
    if not configured():
        raise SolscoreApiUnavailable("SOLSCORE_API_URL, SOLSCORE_API_USERNAME ou SOLSCORE_API_PASSWORD absent de la configuration")

    try:
        # Durée enregistrée sous « solscore_api » dans l'audit (additionnée sur les appels de la requête).
        with timed("solscore_api"), httpx.Client(base_url=config.solscore_api_url.rstrip("/"), timeout=TIMEOUT_SECONDS, transport=transport) as client:
            response = _post(client, route, body, _current_token(client))
            if response.status_code == 401:
                response = _post(client, route, body, _renewed_token(client))
            response.raise_for_status()
            return response.json()
    # Erreur réseau, délai dépassé, identifiants refusés, statut d'erreur, ou réponse qui n'est pas du JSON (ValueError).
    except (httpx.HTTPError, ValueError) as error:
        raise SolscoreApiUnavailable(f"{route} : {type(error).__name__}: {error}") from error


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
