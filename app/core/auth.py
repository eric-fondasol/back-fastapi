import hmac
from functools import lru_cache

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import config

bearer = HTTPBearer(auto_error=False)

DEV_TOKEN_MIN_LENGTH = 32


@lru_cache
def jwks_client() -> jwt.PyJWKClient:
    discovery = httpx.get(f"{config.oidc_issuer}/.well-known/openid-configuration", timeout=10)
    discovery.raise_for_status()
    return jwt.PyJWKClient(discovery.json()["jwks_uri"], lifespan=3600)


def dev_token() -> str | None:
    if config.auth_dev_token is None:
        return None

    token = config.auth_dev_token.get_secret_value()

    if config.app_env != "dev":
        raise RuntimeError("AUTH_DEV_TOKEN is only allowed with APP_ENV=dev")

    if len(token) < DEV_TOKEN_MIN_LENGTH:
        raise RuntimeError(f"AUTH_DEV_TOKEN must be at least {DEV_TOKEN_MIN_LENGTH} characters long")

    return token


def unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"})


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    if credentials is None:
        raise unauthorized()

    expected_dev_token = dev_token()

    if expected_dev_token and hmac.compare_digest(credentials.credentials.encode(), expected_dev_token.encode()):
        return config.auth_dev_user

    try:
        signing_key = jwks_client().get_signing_key_from_jwt(credentials.credentials)
        claims = jwt.decode(
            credentials.credentials,
            signing_key.key,
            algorithms=["RS256"],
            audience=config.oidc_audience,
            issuer=config.oidc_issuer,
            options={"require": ["exp", "iss", "aud"]},
        )
    except (jwt.PyJWTError, httpx.HTTPError):
        raise unauthorized() from None

    username = claims.get("preferred_username")

    if not username:
        raise unauthorized()

    return username
