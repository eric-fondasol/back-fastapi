import hmac
import os
from functools import lru_cache

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


@lru_cache
def jwks_client() -> jwt.PyJWKClient:
    # Clés gardées en mémoire par worker : le JWKS d'Azure n'est pas retéléchargé à chaque requête.
    discovery = httpx.get(f"{os.environ['OIDC_ISSUER']}/.well-known/openid-configuration", timeout=10)
    discovery.raise_for_status()
    return jwt.PyJWKClient(discovery.json()["jwks_uri"], lifespan=3600)


def dev_token() -> str | None:
    """Jeton fixe pour le développement (AUTH_DEV_TOKEN), accepté seulement si APP_ENV=dev."""
    token = os.getenv("AUTH_DEV_TOKEN")
    if not token:
        return None
    if os.getenv("APP_ENV") != "dev":
        raise RuntimeError("AUTH_DEV_TOKEN n'est autorisé qu'avec APP_ENV=dev")
    if len(token) < 32:
        raise RuntimeError("AUTH_DEV_TOKEN doit faire au moins 32 caractères")
    return token


def unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"})


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    """Id token Azure de l'utilisateur, validé comme le fait le back Symfony (OidcTokenHandler)."""
    if credentials is None:
        raise unauthorized()
    token = dev_token()
    if token and hmac.compare_digest(credentials.credentials.encode(), token.encode()):
        return os.getenv("AUTH_DEV_USER", "dev@fondasol.fr")
    try:
        key = jwks_client().get_signing_key_from_jwt(credentials.credentials)
        claims = jwt.decode(
            credentials.credentials,
            key.key,
            algorithms=["RS256"],
            audience=os.environ["OIDC_AUDIENCE"],
            issuer=os.environ["OIDC_ISSUER"],
            options={"require": ["exp", "iss", "aud"]},
        )
    except (jwt.PyJWTError, httpx.HTTPError):
        raise unauthorized()
    username = claims.get("preferred_username")
    if not username:
        raise unauthorized()
    return username
