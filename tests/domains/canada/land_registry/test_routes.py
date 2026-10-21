import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.auth import current_user
from app.domains.canada.land_registry import sources
from app.main import app

ROUTE = "/ca/land-registry/lots"
LOT_4019828 = {
    "type": "Feature",
    "geometry": {
        "type": "Polygon",
        "coordinates": [[[-72.9373, 46.2600], [-72.9370, 46.2600], [-72.9369, 46.2603], [-72.9373, 46.2600]]],
    },
    "properties": {"NO_LOT": "4 019 828"},
}


@pytest.fixture(scope="module")
def client():
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.mark.parametrize("typed", ["4019828", "4 019 828", " 4 0 1 9 8 2 8 ", "0004019828"])
def test_a_lot_is_found_whatever_the_spacing_typed(client, monkeypatch, typed):
    asked = []
    monkeypatch.setattr(sources, "lot_features", lambda number: asked.append(number) or [LOT_4019828])

    response = client.post(ROUTE, json={"lot": typed})

    assert response.status_code == 200
    assert asked == ["4 019 828"]
    assert response.json()["features"][0]["properties"] == {"no_lot": "4 019 828"}
    assert response.json()["features"][0]["geometry"]["type"] == "Polygon"


def test_an_unknown_lot_answers_404(client, monkeypatch):
    monkeypatch.setattr(sources, "lot_features", lambda number: [])

    response = client.post(ROUTE, json={"lot": "123"})

    assert (response.status_code, response.json()) == (404, {"detail": "Lot 123 introuvable"})


@pytest.mark.parametrize("lot", ["", "4019828' OR '1'='1", "AB12", "1" * 21])
def test_refuses_anything_but_digits_and_spaces_before_calling_the_service(client, monkeypatch, lot):
    monkeypatch.setattr(sources, "lot_features", lambda number: pytest.fail("service appelé"))

    assert client.post(ROUTE, json={"lot": lot}).status_code == 422


def test_the_service_query_asks_for_the_lot_in_wgs84(monkeypatch):
    seen = {}

    def fake_get(url, params, timeout):
        seen.update(url=url, params=params)
        return httpx.Response(200, json={"type": "FeatureCollection", "features": [LOT_4019828]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(sources.httpx, "get", fake_get)

    assert sources.lot_features("4 019 828") == [LOT_4019828]
    assert seen["url"] == sources.CADASTRE_ALLEGE_QUERY_URL
    assert (seen["params"]["where"], seen["params"]["outSR"], seen["params"]["f"]) == ("NO_LOT = '4 019 828'", "4326", "geojson")


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(500, text="panne"),
        httpx.Response(200, json={"error": {"code": 400, "message": "Unable to complete operation."}}),
        httpx.Response(200, text="<html>maintenance</html>"),
    ],
)
def test_a_failing_service_answers_502(client, monkeypatch, answer):
    answer.request = httpx.Request("GET", sources.CADASTRE_ALLEGE_QUERY_URL)
    monkeypatch.setattr(sources.httpx, "get", lambda url, params, timeout: answer)

    response = client.post(ROUTE, json={"lot": "4019828"})

    assert (response.status_code, response.json()) == (502, {"detail": "Cadastre du Québec injoignable"})
