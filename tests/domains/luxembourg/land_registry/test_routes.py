import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.auth import current_user
from app.domains.luxembourg.land_registry import services, sources
from app.main import app

ROUTE = "/lu/land-registry/parcels/at"
POINT = {"longitude": 6.1301, "latitude": 49.6111}
SQUARE = [[6.1300, 49.6110], [6.1302, 49.6110], [6.1302, 49.6112], [6.1300, 49.6112], [6.1300, 49.6110]]
PARCEL = {
    "type": "Feature",
    "id": "CP.CadastralParcel.PARCELLES.075F00405002684",
    "geometry": {"type": "Polygon", "coordinates": [SQUARE]},
    "properties": {
        "label": "405/2684",
        "area": 233.76,
        "area_uom": "m2",
        "national_cadastral_reference": "075F00405002684",
        "zoning": "http://catalog.inspire.geoportail.lu/geonetwork/dataset/df8407cc/LIMADM_SECTIONS.75F",
    },
}
ZONING = [
    {"type": "Feature", "geometry": None, "properties": {"label": "Ville Haute", "level_name": "Section", "national_cadastral_zoning_reference": "075F"}},
    {"type": "Feature", "geometry": None, "properties": {"label": "Luxembourg", "level_name": "Cadastral Municipality", "national_cadastral_zoning_reference": "075"}},
]


@pytest.fixture(scope="module")
def client():
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def forgotten_zonings(monkeypatch):
    monkeypatch.setattr(services, "_zonings", {})


def test_the_parcel_under_a_point_comes_with_its_official_area_section_and_municipality(client, monkeypatch):
    asked = []
    monkeypatch.setattr(sources, "parcel_features_at", lambda longitude, latitude: asked.append((longitude, latitude)) or [PARCEL])
    monkeypatch.setattr(sources, "zoning_features_at", lambda longitude, latitude: ZONING)

    response = client.post(ROUTE, json=POINT)

    assert response.status_code == 200
    assert asked == [(6.1301, 49.6111)]
    feature = response.json()["features"][0]
    assert feature["geometry"]["type"] == "Polygon"
    assert feature["properties"] == {
        "reference": "075F00405002684",
        "number": "405/2684",
        "area_m2": 233.76,
        "municipality": "Luxembourg",
        "section": "F",
        "section_name": "Ville Haute",
    }


def test_the_zoning_of_a_section_is_asked_once_then_remembered(client, monkeypatch):
    asked = []
    monkeypatch.setattr(sources, "parcel_features_at", lambda longitude, latitude: [PARCEL])
    monkeypatch.setattr(sources, "zoning_features_at", lambda longitude, latitude: asked.append((longitude, latitude)) or ZONING)

    for _ in range(3):
        assert client.post(ROUTE, json=POINT).json()["features"][0]["properties"]["municipality"] == "Luxembourg"

    assert len(asked) == 1


def test_a_point_outside_any_parcel_answers_404_without_asking_the_zoning(client, monkeypatch):
    monkeypatch.setattr(sources, "parcel_features_at", lambda longitude, latitude: [])
    monkeypatch.setattr(sources, "zoning_features_at", lambda longitude, latitude: pytest.fail("découpage demandé"))

    response = client.post(ROUTE, json=POINT)

    assert (response.status_code, response.json()) == (404, {"detail": "Aucune parcelle à cet endroit"})


@pytest.mark.parametrize("body", [{}, {"longitude": -200, "latitude": 49}, {"longitude": 6, "latitude": 95}, {"longitude": "x", "latitude": 49}])
def test_refuses_a_point_off_the_globe_before_calling_the_service(client, monkeypatch, body):
    monkeypatch.setattr(sources, "parcel_features_at", lambda longitude, latitude: pytest.fail("service appelé"))

    assert client.post(ROUTE, json=body).status_code == 422


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(500, text="panne"),
        httpx.Response(200, text='<?xml version="1.0"?><ows:ExceptionReport/>'),
        httpx.Response(200, json={"error": "inattendu"}),
    ],
)
def test_a_failing_service_answers_502(client, monkeypatch, answer):
    answer.request = httpx.Request("GET", sources.CADASTRAL_PARCELS_WFS_URL)
    monkeypatch.setattr(sources.httpx, "get", lambda url, params, timeout: answer)

    response = client.post(ROUTE, json=POINT)

    assert (response.status_code, response.json()) == (502, {"detail": "Cadastre du Luxembourg injoignable"})


def test_the_point_query_asks_for_the_parcel_intersecting_the_point_in_latitude_longitude_order(monkeypatch):
    seen = {}

    def fake_get(url, params, timeout):
        seen.update(url=url, params=params)
        return httpx.Response(200, json={"type": "FeatureCollection", "features": [PARCEL]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(sources.httpx, "get", fake_get)

    assert sources.parcel_features_at(6.1301, 49.6111) == [PARCEL]
    assert seen["url"] == "https://wms.inspire.geoportail.lu/geoserver/cp/wfs"
    params = seen["params"]
    assert (params["TYPENAMES"], params["OUTPUTFORMAT"], params["SRSNAME"]) == ("cp:CP.CadastralParcel", "application/json", "EPSG:4326")
    assert "<gml:pos>49.6111 6.1301</gml:pos>" in params["FILTER"]
    assert "PROPERTYNAME" not in params


def test_the_zoning_query_leaves_out_the_geometries(monkeypatch):
    seen = {}

    def fake_get(url, params, timeout):
        seen.update(params=params)
        return httpx.Response(200, json={"type": "FeatureCollection", "features": ZONING}, request=httpx.Request("GET", url))

    monkeypatch.setattr(sources.httpx, "get", fake_get)

    assert sources.zoning_features_at(6.1301, 49.6111) == ZONING
    assert (seen["params"]["TYPENAMES"], seen["params"]["PROPERTYNAME"]) == ("cp:CP.CadastralZoning", "label,level_name,national_cadastral_zoning_reference")
