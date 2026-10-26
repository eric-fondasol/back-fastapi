import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.auth import current_user
from app.domains.layer_catalog import sources
from app.main import app
from tests.domains.layer_catalog.test_gml import GML2_POLYGON_WITH_HOLE

VERSIONS = Path(__file__).parents[3] / "migrations" / "versions"
PARIS = "2.2,48.8,2.5,48.95"


def migration(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def client(refonte_database):
    with refonte_database.begin() as connection:
        for name in ("0007_layer_catalog", "0008_layer_catalog_france", "0009_catalog_feature_layers"):
            migration(name).seed(connection)
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


class Upstream:
    def __init__(self, monkeypatch, content=b"", status=200, error=None):
        self.calls = []

        def get(url, params, timeout, follow_redirects):
            self.calls.append((url, params))
            if error is not None:
                raise error
            return httpx.Response(status, content=content, request=httpx.Request("GET", url))

        monkeypatch.setattr(sources.httpx, "get", get)


def features_of(client, code, bbox=PARIS, zoom=10):
    return client.get(f"/layer-catalog/{code}/features", params={"bbox": bbox, "zoom": zoom})


def test_the_ten_vector_layers_are_in_the_catalog(client):
    layers = {layer["code"]: layer for layer in client.get("/layer-catalog").json()["layers"]}

    vector = {code: layer["kind"] for code, layer in layers.items() if layer["kind"] in ("wfs", "geojson")}

    assert len(vector) == 10
    assert vector["fr-ades-piezometres"] == "geojson"
    assert layers["fr-inpn-natura2000-zsc-sic"]["minZoom"] == 9.0
    assert layers["fr-inpn-zico"]["url"].startswith("http://")


def test_a_mapserver_layer_is_asked_in_latitude_longitude_and_answered_in_longitude_latitude(client, monkeypatch):
    upstream = Upstream(monkeypatch, content=GML2_POLYGON_WITH_HOLE.encode())

    response = features_of(client, "fr-inpn-zico", bbox="1.4,48.8,1.8,49.2")

    assert response.status_code == 200
    url, params = upstream.calls[0]
    assert url == "http://ws.carmencarto.fr/WFS/119/fxx_inpn"
    assert params["BBOX"] == "48.8,1.4,49.2,1.8,EPSG:4326"
    assert (params["TYPENAME"], params["VERSION"], params["MAXFEATURES"]) == ("ZICO", "1.1.0", sources.MAX_FEATURES)
    body = response.json()
    assert body["type"] == "FeatureCollection" and body["truncated"] is False
    [feature] = body["features"]
    assert feature["properties"]["NOM"] == "Vallée de la Seine"
    assert feature["geometry"]["coordinates"][0][0] == pytest.approx([1.5, 48.9], abs=0.001)


def test_a_geojson_wfs_is_asked_in_longitude_latitude_with_count(client, monkeypatch):
    collection = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [2.3, 48.9]}, "properties": {"code_18": "112"}}]}
    upstream = Upstream(monkeypatch, content=json.dumps(collection).encode())

    response = features_of(client, "fr-clc-2018", zoom=13)

    _, params = upstream.calls[0]
    assert params["BBOX"] == "2.2,48.8,2.5,48.95,EPSG:4326"
    assert params["TYPENAMES"] == "LANDCOVER.CLC18_FR:clc18_fr" and params["COUNT"] == sources.MAX_FEATURES
    assert response.json()["features"][0]["properties"] == {"code_18": "112"}


def test_hubeau_gets_the_bbox_in_its_own_parameter_and_a_capped_size(client, monkeypatch):
    points = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [2.3, 48.9]}, "properties": {"libelle_pe": "P", "codes": ["x"]}}]
    upstream = Upstream(monkeypatch, content=json.dumps({"type": "FeatureCollection", "features": points * sources.MAX_FEATURES}).encode())

    body = features_of(client, "fr-ades-piezometres").json()

    _, params = upstream.calls[0]
    assert params == {"format": "geojson", "size": str(sources.MAX_FEATURES), "bbox": "2.2,48.8,2.5,48.95"}
    assert body["truncated"] is True
    assert body["features"][0]["properties"] == {"libelle_pe": "P"}


def test_below_the_minimum_zoom_the_service_is_not_called(client, monkeypatch):
    upstream = Upstream(monkeypatch)

    response = features_of(client, "fr-inpn-natura2000-zsc-sic", zoom=8)

    assert response.json() == {"type": "FeatureCollection", "features": [], "truncated": False}
    assert upstream.calls == []


@pytest.mark.parametrize("code", ["fr-inconnue", "fr-geologie"])
def test_an_unknown_code_or_an_image_layer_answers_404(client, code):
    assert features_of(client, code).status_code == 404


@pytest.mark.parametrize("bbox", ["2,48,3", "a,b,c,d", "3,48,2,49", "-10,30,30,60", "2,48,3,95"])
def test_an_invalid_or_too_large_bbox_answers_400(client, bbox):
    assert features_of(client, "fr-inpn-zico", bbox=bbox).status_code == 400


@pytest.mark.parametrize(
    "upstream",
    [
        {"status": 503},
        {"error": httpx.ConnectError("refusée")},
        {"content": b"<html>erreur</html>"},
    ],
)
def test_a_failing_service_answers_502(client, monkeypatch, upstream):
    Upstream(monkeypatch, **upstream)

    assert features_of(client, "fr-inpn-zico").status_code == 502


def test_a_request_without_token_is_refused(client):
    app.dependency_overrides.clear()

    assert features_of(client, "fr-inpn-zico").status_code == 401
