import pytest
from fastapi.testclient import TestClient

from app.core.auth import current_user
from app.main import app

PARIS = {"minLat": 48.84, "maxLat": 48.87, "minLng": 2.33, "maxLng": 2.37}
ATLANTIC_OCEAN = {"minLat": -40.0, "maxLat": -39.9, "minLng": -30.0, "maxLng": -29.9}

EXPECTED_PROPERTIES = {
    "/searchSitesByArea": set(),
    "/searchSitesByAreaDetails": {"uuid", "affaire_id", "affaire_numero", "affaire_nom"},
    "/searchSurveysByArea": set(),
    "/searchSurveysByAreaDetails": {"id", "nom", "site_uuid", "has_mesure_pressiometrique"},
}


@pytest.fixture(scope="module")
def client():
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def search(client, route, bounds):
    return client.post(route, json={"bounds": bounds})


@pytest.mark.parametrize("route", EXPECTED_PROPERTIES)
def test_an_area_returns_a_geojson_collection_of_points_within_bounds(client, route):
    response = search(client, route, PARIS)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"

    collection = response.json()

    assert collection["type"] == "FeatureCollection"
    assert collection["features"]

    for feature in collection["features"]:
        longitude, latitude = feature["geometry"]["coordinates"]

        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] == "Point"
        assert PARIS["minLng"] <= longitude <= PARIS["maxLng"]
        assert PARIS["minLat"] <= latitude <= PARIS["maxLat"]
        assert round(longitude, 6) == longitude and round(latitude, 6) == latitude
        assert set(feature["properties"]) == EXPECTED_PROPERTIES[route]


def test_the_pressiometric_flag_is_always_a_boolean(client):
    features = search(client, "/searchSurveysByAreaDetails", PARIS).json()["features"]

    assert all(isinstance(feature["properties"]["has_mesure_pressiometrique"], bool) for feature in features)


@pytest.mark.parametrize("route", EXPECTED_PROPERTIES)
def test_an_area_without_data_returns_an_empty_collection(client, route):
    response = search(client, route, ATLANTIC_OCEAN)

    assert response.status_code == 200
    assert response.json() == {"type": "FeatureCollection", "features": []}


@pytest.mark.parametrize(
    "bounds",
    [
        pytest.param(PARIS | {"minLat": 48.87, "maxLat": 48.84}, id="swapped latitudes"),
        pytest.param(PARIS | {"minLng": 2.37, "maxLng": 2.33}, id="swapped longitudes"),
        pytest.param(PARIS | {"maxLat": 91}, id="latitude out of range"),
        pytest.param(PARIS | {"minLng": -181}, id="longitude out of range"),
        pytest.param({"minLat": 48.84, "maxLat": 48.87}, id="incomplete bounds"),
    ],
)
def test_invalid_bounds_are_rejected(client, bounds):
    assert search(client, "/searchSurveysByAreaDetails", bounds).status_code == 422


def test_a_request_without_bounds_is_rejected(client):
    assert client.post("/searchSurveysByAreaDetails", json={}).status_code == 422
