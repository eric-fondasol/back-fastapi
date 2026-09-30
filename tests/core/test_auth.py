import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core import auth
from app.core.config import config
from app.main import app

ISSUER = "https://login.microsoftonline.com/test-tenant/v2.0"
AUDIENCE = "test-application"
BODY = {"bounds": {"minLat": 48.84, "maxLat": 48.87, "minLng": 2.33, "maxLng": 2.37}}
DEV_TOKEN = "dev-token-" + "x" * 32

signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
foreign_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJwksClient:
    def get_signing_key_from_jwt(self, _token):
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
        return jwt.PyJWK.from_dict(jwk | {"alg": "RS256"})


def id_token(key=signing_key, **overrides):
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": int(time.time()) + 3600,
        "preferred_username": "jean.dupont@fondasol.fr",
    } | overrides
    return jwt.encode({name: value for name, value in claims.items() if value is not None}, key, algorithm="RS256")


@pytest.fixture(autouse=True)
def test_configuration(monkeypatch):
    monkeypatch.setattr(config, "oidc_issuer", ISSUER)
    monkeypatch.setattr(config, "oidc_audience", AUDIENCE)
    monkeypatch.setattr(config, "app_env", "prod")
    monkeypatch.setattr(config, "auth_dev_token", None)
    monkeypatch.setattr(auth, "jwks_client", FakeJwksClient)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def call(client, token=None, route="/searchSitesByArea"):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(route, json=BODY, headers=headers)


def test_health_check_stays_public(client):
    assert client.get("/api/health").status_code != 401


@pytest.mark.parametrize(
    "route", ["/searchSitesByArea", "/searchSitesByAreaDetails", "/searchSurveysByArea", "/searchSurveysByAreaDetails"]
)
def test_a_route_without_token_is_rejected(client, route):
    response = call(client, route=route)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_a_valid_id_token_is_accepted(client):
    assert call(client, id_token()).status_code == 200


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(id_token(key=foreign_key), id="signed with another key"),
        pytest.param(id_token(aud="other-application"), id="other audience"),
        pytest.param(id_token(iss="https://login.microsoftonline.com/other-tenant/v2.0"), id="other tenant"),
        pytest.param(id_token(exp=int(time.time()) - 60), id="expired"),
        pytest.param(id_token(preferred_username=None), id="without preferred_username"),
        pytest.param(
            jwt.encode({"iss": ISSUER, "aud": AUDIENCE}, "shared-secret-long-enough-for-hs256", algorithm="HS256"),
            id="HS256",
        ),
        pytest.param("not-a-jwt", id="unreadable"),
    ],
)
def test_an_invalid_token_is_rejected(client, token):
    assert call(client, token).status_code == 401


def test_the_dev_token_is_accepted_in_dev(client, monkeypatch):
    monkeypatch.setattr(config, "app_env", "dev")
    monkeypatch.setattr(config, "auth_dev_token", SecretStr(DEV_TOKEN))

    assert call(client, DEV_TOKEN).status_code == 200
    assert call(client, DEV_TOKEN + "y").status_code == 401


def test_the_dev_token_is_ignored_when_not_configured(client, monkeypatch):
    monkeypatch.setattr(config, "app_env", "dev")

    assert call(client, DEV_TOKEN).status_code == 401


@pytest.mark.parametrize("environment", ["prod", "staging"])
def test_the_dev_token_prevents_startup_outside_dev(monkeypatch, environment):
    monkeypatch.setattr(config, "app_env", environment)
    monkeypatch.setattr(config, "auth_dev_token", SecretStr(DEV_TOKEN))

    with pytest.raises(RuntimeError, match="APP_ENV=dev"):
        with TestClient(app):
            pass


def test_a_too_short_dev_token_prevents_startup(monkeypatch):
    monkeypatch.setattr(config, "app_env", "dev")
    monkeypatch.setattr(config, "auth_dev_token", SecretStr("short"))

    with pytest.raises(RuntimeError, match="32 characters"):
        with TestClient(app):
            pass
