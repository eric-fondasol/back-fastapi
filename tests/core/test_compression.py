import gzip

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.auth import current_user
from app.core.config import config
from app.domains.map import sources
from app.main import app

PARIS = {"minLat": 48.84, "maxLat": 48.87, "minLng": 2.33, "maxLng": 2.37}
SURVEY = {
    "type": "Feature",
    "geometry": {"type": "Point", "coordinates": [2.353003, 48.857975]},
    "properties": {"id": "IP.04.0035_sc2", "name": "sc2", "site_id": "IP.04.0035", "has_pressuremeter": True, "has_penetrometer": False, "has_lithology": True},
}


@pytest.fixture(scope="module")
def client():
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def solscore_api(monkeypatch):
    monkeypatch.setattr(config, "solscore_api_url", "http://solscore-api.test")
    monkeypatch.setattr(config, "solscore_api_username", "service")
    monkeypatch.setattr(config, "solscore_api_password", SecretStr("secret"))
    monkeypatch.setattr(sources, "_token", None)

    def answer(count):
        def handler(request):
            if request.url.path == "/auth":
                return httpx.Response(200, json={"access_token": "token-1"})
            return httpx.Response(200, json={"type": "FeatureCollection", "features": [SURVEY] * count})

        monkeypatch.setattr(sources, "transport", httpx.MockTransport(handler))

    return answer


def raw_post(client, accept_encoding):
    with client.stream("POST", "/searchSurveysByAreaDetails", json={"bounds": PARIS}, headers={"Accept-Encoding": accept_encoding}) as response:
        return response, b"".join(response.iter_raw())


def test_a_large_json_response_is_gzipped_when_the_client_accepts_it(client, solscore_api):
    solscore_api(500)

    response, body = raw_post(client, "gzip")

    assert response.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in response.headers["vary"]
    assert len(gzip.decompress(body)) > 10 * len(body)
    assert gzip.decompress(body).startswith(b'{"type":"FeatureCollection"')


def test_a_client_that_does_not_accept_gzip_gets_plain_json(client, solscore_api):
    solscore_api(500)

    response, body = raw_post(client, "identity")

    assert "content-encoding" not in response.headers
    assert body.startswith(b'{"type":"FeatureCollection"')


def test_a_small_response_is_not_compressed(client, solscore_api):
    solscore_api(0)

    response, body = raw_post(client, "gzip")

    assert "content-encoding" not in response.headers
    assert body == b'{"type":"FeatureCollection","features":[]}'
