import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import auth
from app.main import app

ISSUER = "https://login.microsoftonline.com/tenant-de-test/v2.0"
AUDIENCE = "application-de-test"
BODY = {"bounds": {"minLat": 48.84, "maxLat": 48.87, "minLng": 2.33, "maxLng": 2.37}}

signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
foreign_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJwksClient:
    def get_signing_key_from_jwt(self, _token):
        return jwt.PyJWK.from_dict(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True) | {"alg": "RS256"})


def id_token(key=signing_key, **overrides):
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": int(time.time()) + 3600,
        "preferred_username": "jean.dupont@fondasol.fr",
    } | overrides
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="RS256")


@pytest.fixture(scope="module")
def client():
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("OIDC_ISSUER", ISSUER)
        patch.setenv("OIDC_AUDIENCE", AUDIENCE)
        patch.setattr(auth, "jwks_client", FakeJwksClient)
        with TestClient(app) as test_client:
            yield test_client


def post(client, token=None, path="/searchSitesByArea"):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(path, json=BODY, headers=headers)


def test_health_reste_public(client):
    assert client.get("/api/health").status_code != 401


@pytest.mark.parametrize("path", ["/searchSitesByArea", "/searchSitesByAreaDetails", "/searchSurveysByArea", "/searchSurveysByAreaDetails"])
def test_une_route_sans_jeton_est_refusee(client, path):
    response = post(client, path=path)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_un_id_token_valide_est_accepte(client):
    assert post(client, id_token()).status_code == 200


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(id_token(key=foreign_key), id="signature d'une autre clé"),
        pytest.param(id_token(aud="autre-application"), id="autre audience"),
        pytest.param(id_token(iss="https://login.microsoftonline.com/autre-tenant/v2.0"), id="autre tenant"),
        pytest.param(id_token(exp=int(time.time()) - 60), id="expiré"),
        pytest.param(id_token(preferred_username=None), id="sans preferred_username"),
        pytest.param(jwt.encode({"iss": ISSUER, "aud": AUDIENCE}, "secret-partage-assez-long-pour-hs256", algorithm="HS256"), id="HS256"),
        pytest.param("pas-un-jwt", id="illisible"),
    ],
)
def test_un_jeton_invalide_est_refuse(client, token):
    assert post(client, token).status_code == 401


DEV_TOKEN = "jeton-de-dev-" + "x" * 32


def test_le_jeton_de_dev_est_accepte_en_dev(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("AUTH_DEV_TOKEN", DEV_TOKEN)
    assert post(client, DEV_TOKEN).status_code == 200
    assert post(client, DEV_TOKEN + "y").status_code == 401


def test_le_jeton_de_dev_est_ignore_sans_configuration(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.delenv("AUTH_DEV_TOKEN", raising=False)
    assert post(client, DEV_TOKEN).status_code == 401


@pytest.mark.parametrize("app_env", [None, "prod"])
def test_le_jeton_de_dev_empeche_de_demarrer_hors_dev(monkeypatch, app_env):
    if app_env:
        monkeypatch.setenv("APP_ENV", app_env)
    else:
        monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("AUTH_DEV_TOKEN", DEV_TOKEN)
    with pytest.raises(RuntimeError, match="APP_ENV=dev"):
        with TestClient(app):
            pass


def test_un_jeton_de_dev_trop_court_empeche_de_demarrer(monkeypatch):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("AUTH_DEV_TOKEN", "court")
    with pytest.raises(RuntimeError, match="32 caractères"):
        with TestClient(app):
            pass
