import importlib.util
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.auth import current_user
from app.core.config import config
from app.domains.layer_catalog import sources
from app.main import app

VERSIONS = Path(__file__).parents[3] / "migrations" / "versions"
API_KEY = "cle-de-test"
SCAN25_TILE = "/layer-catalog/fr-ign-scan25/tiles/12/2074/1409"
JPEG = b"\xff\xd8\xff\xe0tuile"


def migration(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def client(refonte_database, monkeypatch):
    with refonte_database.begin() as connection:
        for name in ("0007_layer_catalog", "0008_layer_catalog_france", "0009_catalog_feature_layers", "0010_catalog_scan25"):
            migration(name).seed(connection)
    monkeypatch.setattr(config, "ign_private_api_key", SecretStr(API_KEY))
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


class Upstream:
    def __init__(self, monkeypatch, content=JPEG, status=200, content_type="image/jpeg", error=None):
        self.calls = []

        def get(url, params, timeout, follow_redirects):
            self.calls.append((url, params))
            if error is not None:
                raise error
            return httpx.Response(status, content=content, headers={"content-type": content_type}, request=httpx.Request("GET", url))

        monkeypatch.setattr(sources.httpx, "get", get)


def catalog_codes(client):
    return {layer["code"]: layer for layer in client.get("/layer-catalog").json()["layers"]}


def test_the_scan25_is_in_the_catalog_without_its_key(client):
    scan25 = catalog_codes(client)["fr-ign-scan25"]

    assert (scan25["category"], scan25["kind"], scan25["minZoom"], scan25["maxZoom"]) == ("topographie", "wmts", 6.0, 16.0)
    assert scan25["params"] == {
        "layer": "GEOGRAPHICALGRIDSYSTEMS.MAPS.SCAN25TOUR",
        "style": "normal",
        "tileMatrixSet": "PM_6_16",
        "format": "image/jpeg",
        "relayed": True,
    }
    assert API_KEY not in str(client.get("/layer-catalog").json())


def test_without_a_key_the_relayed_layer_leaves_the_catalog_and_its_tiles_are_unknown(client, monkeypatch):
    monkeypatch.setattr(config, "ign_private_api_key", None)
    upstream = Upstream(monkeypatch)

    assert "fr-ign-scan25" not in catalog_codes(client)
    assert "fr-ign-carte-etat-major-40k" in catalog_codes(client)
    assert client.get(SCAN25_TILE).status_code == 404
    assert upstream.calls == []


def test_a_tile_is_asked_to_the_private_service_with_the_key(client, monkeypatch):
    upstream = Upstream(monkeypatch)

    response = client.get(SCAN25_TILE)

    assert response.status_code == 200
    assert response.content == JPEG
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, max-age=86400"
    [(url, params)] = upstream.calls
    assert url == "https://data.geopf.fr/private/wmts"
    assert params["apikey"] == API_KEY
    assert (params["LAYER"], params["TILEMATRIXSET"], params["FORMAT"]) == ("GEOGRAPHICALGRIDSYSTEMS.MAPS.SCAN25TOUR", "PM_6_16", "image/jpeg")
    assert (params["TILEMATRIX"], params["TILECOL"], params["TILEROW"]) == (12, 2074, 1409)


@pytest.mark.parametrize("code", ["fr-ign-carte-etat-major-40k", "fr-inpn-zico", "inconnue"])
def test_only_a_relayed_layer_has_its_tiles_relayed(client, monkeypatch, code):
    upstream = Upstream(monkeypatch)

    assert client.get(f"/layer-catalog/{code}/tiles/12/2074/1409").status_code == 404
    assert upstream.calls == []


@pytest.mark.parametrize("path", ["/layer-catalog/fr-ign-scan25/tiles/2/4/0", "/layer-catalog/fr-ign-scan25/tiles/23/0/0", "/layer-catalog/fr-ign-scan25/tiles/5/-1/0"])
def test_a_tile_outside_the_grid_is_refused(client, monkeypatch, path):
    upstream = Upstream(monkeypatch)

    assert client.get(path).status_code in (400, 422)
    assert upstream.calls == []


@pytest.mark.parametrize("status", [400, 404])
def test_a_tile_the_service_does_not_have_is_a_404(client, monkeypatch, status):
    Upstream(monkeypatch, content=b"<ExceptionReport/>", status=status, content_type="application/xml")

    assert client.get(SCAN25_TILE).status_code == 404


@pytest.mark.parametrize(
    "upstream",
    [
        {"status": 403, "content": b"cle refusee"},
        {"content": b"<ExceptionReport/>", "content_type": "application/xml"},
        {"error": httpx.ConnectTimeout("timeout")},
    ],
)
def test_a_refused_key_or_a_failing_service_is_a_502_that_does_not_reveal_the_key(client, monkeypatch, upstream):
    Upstream(monkeypatch, **upstream)

    response = client.get(SCAN25_TILE)

    assert response.status_code == 502
    assert API_KEY not in response.text


def test_a_tile_request_without_token_is_refused(client):
    app.dependency_overrides.clear()

    assert client.get(SCAN25_TILE).status_code == 401
