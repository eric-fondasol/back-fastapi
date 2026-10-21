# Vérification du jeton envoyé par le front : id token Azure AD, ou jeton fixe en développement.
# Branché sur les routeurs dans main.py (dependencies=protected) : toute route métier passe ici.

import hmac
import uuid
from dataclasses import dataclass
from functools import lru_cache

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import config
from app.core.timing import timed

# Lit l'en-tête « Authorization: Bearer <jeton> ». auto_error=False : un en-tête absent donne
# None au lieu d'une erreur de FastAPI, pour que ce module réponde lui-même un 401 uniforme.
bearer = HTTPBearer(auto_error=False)

DEV_TOKEN_MIN_LENGTH = 32


# Client qui fournit les clés publiques de signature d'Azure (JWKS).
# lru_cache : créé une seule fois pour toute la vie de l'API (une erreur n'est pas mise en cache,
# l'appel suivant réessaie). Préchargé au démarrage par core/warmup.py.
@lru_cache
def jwks_client() -> jwt.PyJWKClient:
    # Le document de découverte OpenID du tenant indique où Azure publie ses clés (jwks_uri).
    discovery = httpx.get(f"{config.oidc_issuer}/.well-known/openid-configuration", timeout=10)
    discovery.raise_for_status()
    # lifespan=3600 : les clés sont gardées en mémoire une heure, puis rechargées.
    return jwt.PyJWKClient(discovery.json()["jwks_uri"], lifespan=3600)


# Renvoie le jeton de développement s'il est défini, après avoir vérifié qu'il est autorisé.
# Appelé aussi au démarrage (lifespan dans main.py) : une configuration interdite empêche l'API de démarrer.
def dev_token() -> str | None:
    if config.auth_dev_token is None:
        return None

    token = config.auth_dev_token.get_secret_value()

    # Garde-fou : ce jeton fixe ne doit jamais être accepté hors d'un poste de développement.
    if config.app_env != "dev":
        raise RuntimeError("AUTH_DEV_TOKEN is only allowed with APP_ENV=dev")

    # Garde-fou : un jeton court serait facile à deviner.
    if len(token) < DEV_TOKEN_MIN_LENGTH:
        raise RuntimeError(f"AUTH_DEV_TOKEN must be at least {DEV_TOKEN_MIN_LENGTH} characters long")

    return token


# Réponse 401 commune à tous les refus, sans détail sur la cause pour ne rien révéler à l'appelant.
def unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"})


# Qui appelle, d'après le jeton : son adresse, son identifiant Azure (oid) et son nom affiché.
# oid et name peuvent manquer (jeton sans ces claims) ; core/profile.py exige l'oid.
@dataclass(frozen=True)
class Identity:
    username: str
    azure_oid: str | None = None
    name: str | None = None


# Dépendance FastAPI : vérifie le jeton et renvoie l'identité de l'appelant.
# FastAPI ne l'exécute qu'une fois par requête, même si plusieurs dépendances la demandent.
def current_identity(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Identity:
    # Chronomètre la vérification : la durée apparaît dans details.timings_ms.auth de l'audit.
    with timed("auth"):
        identity = verified_identity(credentials)

    # Rendu disponible au middleware d'audit (core/audit.py), qui l'écrit dans audit_log.username.
    request.state.username = identity.username
    return identity


# Dépendance FastAPI exécutée avant chaque route protégée. Renvoie l'adresse de l'agent connecté.
def current_user(identity: Identity = Depends(current_identity)) -> str:
    return identity.username


# Identité du jeton de développement : l'oid est dérivé de l'adresse, pour rester le même d'un
# démarrage à l'autre (le profil créé en base est ainsi retrouvé).
def dev_identity() -> Identity:
    return Identity(config.auth_dev_user, str(uuid.uuid5(uuid.NAMESPACE_URL, f"solscore-dev:{config.auth_dev_user}")))


# Vérifie le jeton et renvoie l'identité qu'il contient ; lève un 401 au moindre problème.
def verified_identity(credentials: HTTPAuthorizationCredentials | None) -> Identity:
    # Pas d'en-tête Authorization, ou pas au format « Bearer … ».
    if credentials is None:
        raise unauthorized()

    expected_dev_token = dev_token()

    # Jeton de développement : comparaison en temps constant, pour qu'on ne puisse pas le deviner
    # caractère par caractère en mesurant le temps de réponse.
    if expected_dev_token and hmac.compare_digest(credentials.credentials.encode(), expected_dev_token.encode()):
        return dev_identity()

    try:
        # Choisit la clé publique d'Azure qui correspond à l'identifiant (kid) inscrit dans le jeton.
        signing_key = jwks_client().get_signing_key_from_jwt(credentials.credentials)
        claims = jwt.decode(
            credentials.credentials,
            signing_key.key,
            # Seul RS256 est accepté : bloque les jetons forgés en « none » ou en HS256.
            algorithms=["RS256"],
            # Le jeton doit avoir été émis pour notre application…
            audience=config.oidc_audience,
            # … par notre tenant Azure.
            issuer=config.oidc_issuer,
            # Ces champs doivent être présents ; exp est en plus contrôlé (jeton non expiré).
            options={"require": ["exp", "iss", "aud"]},
        )
    # Jeton invalide (signature, audience, émetteur, expiration…) ou Azure injoignable : 401.
    # « from None » évite d'attacher l'erreur d'origine à la réponse.
    except (jwt.PyJWTError, httpx.HTTPError):
        raise unauthorized() from None

    # L'adresse de l'agent (ex. prenom.nom@fondasol.fr) ; sans elle, on ne sait pas qui appelle.
    username = claims.get("preferred_username")

    if not username:
        raise unauthorized()

    return Identity(username, _text_claim(claims, "oid"), _text_claim(claims, "name"))


# Valeur texte d'un claim, ou None s'il est absent, vide ou d'un autre type.
def _text_claim(claims: dict, name: str) -> str | None:
    value = claims.get(name)
    return value if isinstance(value, str) and value.strip() else None
