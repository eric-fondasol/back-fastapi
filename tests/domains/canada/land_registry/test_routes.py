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
    assert response.json()["features"][0]["properties"]["no_lot"] == "4 019 828"
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


AT_ROUTE = "/ca/land-registry/lots/at"
# Carré de 0,001° de côté vers 46° N : environ 77,3 m d'est en ouest et 111,2 m du sud au nord.
SQUARE = [[-72.938, 46.26], [-72.937, 46.26], [-72.937, 46.261], [-72.938, 46.261], [-72.938, 46.26]]


def lot(geometry):
    return {"type": "Feature", "geometry": geometry, "properties": {"NO_LOT": "4 409 377"}}


def test_the_lot_under_a_clicked_point_is_returned_with_its_computed_area(client, monkeypatch):
    asked = []
    monkeypatch.setattr(sources, "lot_features_at", lambda longitude, latitude: asked.append((longitude, latitude)) or [lot({"type": "Polygon", "coordinates": [SQUARE]})])

    response = client.post(AT_ROUTE, json={"longitude": -72.9375, "latitude": 46.2605})

    assert response.status_code == 200
    assert asked == [(-72.9375, 46.2605)]
    properties = response.json()["features"][0]["properties"]
    assert properties["no_lot"] == "4 409 377"
    assert properties["area_m2"] == pytest.approx(77.3 * 111.2, rel=0.01)


def test_the_area_removes_holes_and_adds_the_parts_of_a_multipolygon(client, monkeypatch):
    hole = [[-72.9378, 46.2602], [-72.9372, 46.2602], [-72.9372, 46.2608], [-72.9378, 46.2608], [-72.9378, 46.2602]]
    shifted = [[x + 0.01, y] for x, y in SQUARE]
    geometry = {"type": "MultiPolygon", "coordinates": [[SQUARE, hole], [shifted]]}
    monkeypatch.setattr(sources, "lot_features_at", lambda longitude, latitude: [lot(geometry)])

    area = client.post(AT_ROUTE, json={"longitude": -72.9375, "latitude": 46.2605}).json()["features"][0]["properties"]["area_m2"]

    square = 77.3 * 111.2
    assert area == pytest.approx(2 * square - 0.36 * square, rel=0.01)


def test_a_point_outside_the_renovated_cadastre_answers_404(client, monkeypatch):
    monkeypatch.setattr(sources, "lot_features_at", lambda longitude, latitude: [])

    response = client.post(AT_ROUTE, json={"longitude": 2.35, "latitude": 48.85})

    assert (response.status_code, response.json()) == (404, {"detail": "Aucun lot à cet endroit"})


@pytest.mark.parametrize("body", [{}, {"longitude": -200, "latitude": 46}, {"longitude": -72, "latitude": 95}, {"longitude": "x", "latitude": 46}])
def test_refuses_a_point_off_the_globe_before_calling_the_service(client, monkeypatch, body):
    monkeypatch.setattr(sources, "lot_features_at", lambda longitude, latitude: pytest.fail("service appelé"))

    assert client.post(AT_ROUTE, json=body).status_code == 422


def test_the_point_query_asks_the_given_service_for_the_lot_containing_the_point(monkeypatch):
    seen = {}

    def fake_get(url, params, timeout):
        seen.update(url=url, params=params)
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []}, request=httpx.Request("GET", url))

    monkeypatch.setattr(sources.httpx, "get", fake_get)

    assert sources.lot_features_at(-73.58, 45.52) == []
    assert seen["url"] == "https://geo.environnement.gouv.qc.ca/donnees/rest/services/Reference/Cadastre_allege/MapServer/0/query"
    params = seen["params"]
    assert (params["geometry"], params["geometryType"], params["inSR"], params["spatialRel"]) == (
        "-73.58,45.52",
        "esriGeometryPoint",
        "4326",
        "esriSpatialRelIntersects",
    )
    assert (params["outFields"], params["outSR"], params["f"], params["maxAllowableOffset"]) == ("NO_LOT", "4326", "geojson", "0.000005")


def test_a_failing_service_on_a_click_answers_502(client, monkeypatch):
    answer = httpx.Response(500, text="panne", request=httpx.Request("GET", sources.CADASTRE_ALLEGE_QUERY_URL))
    monkeypatch.setattr(sources.httpx, "get", lambda url, params, timeout: answer)

    response = client.post(AT_ROUTE, json={"longitude": -73.58, "latitude": 45.52})

    assert (response.status_code, response.json()) == (502, {"detail": "Cadastre du Québec injoignable"})
