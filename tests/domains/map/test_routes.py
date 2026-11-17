import json
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.auth import current_user
from app.core.config import config
from app.core import solscore_api
from app.main import app

SOLSCORE_API = "http://solscore-api.test"
PARIS = {"minLat": 48.84, "maxLat": 48.87, "minLng": 2.33, "maxLng": 2.37}

SITE_IP_08_0106 = {
    "type": "Feature",
    "geometry": {"type": "Point", "coordinates": [2.3467912, 48.8545358]},
    "properties": {
        "id": "IP.08.0106",
        "project_id": "e3630a96-2f57-4fb1-943d-bd675a085181",
        "project_number": "IP.08.0106",
        "project_description": "CONSTRUCTION D'UN CENTRE D'INFORMATION",
    },
}
SURVEY_IP_04_0035_SC2 = {
    "type": "Feature",
    "geometry": {"type": "Point", "coordinates": [2.353003, 48.857975]},
    "properties": {
        "id": "IP.04.0035_sc2",
        "name": "sc2",
        "site_id": "IP.04.0035",
        "has_pressuremeter": None,
        "has_penetrometer": True,
        "has_lithology": True,
        "has_water_levels": False,
        "has_pz_equipment": False,
        "is_survey_fondasol": True,
    },
}
SURVEY_POSITION = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [2.3530031234, 48.8579759876]}, "properties": {}}

ANSWERS = {
    "/general/searchSitesByAreaDetails": [SITE_IP_08_0106],
    "/general/searchSurveysByAreaDetails": [SURVEY_IP_04_0035_SC2],
    "/general/searchSurveysByArea": [SURVEY_POSITION],
}


@pytest.fixture(scope="module")
def client():
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def solscore_api_configuration(monkeypatch):
    monkeypatch.setattr(config, "solscore_api_url", SOLSCORE_API)
    monkeypatch.setattr(config, "solscore_api_username", "service")
    monkeypatch.setattr(config, "solscore_api_password", SecretStr("secret"))
    monkeypatch.setattr(solscore_api, "_token", None)


class SimulatedSolscoreApi:
    def __init__(self, valid_tokens=("token-1",), answers=ANSWERS):
        self.tokens = iter(valid_tokens)
        self.valid_token = None
        self.answers = answers
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if request.url.path == "/auth":
            self.valid_token = next(self.tokens)
            return httpx.Response(200, json={"access_token": self.valid_token, "token_type": "bearer"})
        if request.headers.get("authorization") != f"Bearer {self.valid_token}":
            return httpx.Response(401, json={"detail": "Not authenticated"})
        return httpx.Response(200, json={"type": "FeatureCollection", "features": self.answers[request.url.path]})


def simulate(monkeypatch, handler):
    monkeypatch.setattr(solscore_api, "transport", httpx.MockTransport(handler))
    return handler


def search(client, route, bounds=PARIS):
    return client.post(route, json={"bounds": bounds})


def test_sites_are_read_on_the_solscore_api_and_keep_the_front_contract(client, monkeypatch):
    api = simulate(monkeypatch, SimulatedSolscoreApi())

    response = search(client, "/searchSitesByAreaDetails")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [2.346791, 48.854536]},
                "properties": {
                    "uuid": "IP.08.0106",
                    "affaire_id": "e3630a96-2f57-4fb1-943d-bd675a085181",
                    "affaire_numero": "IP.08.0106",
                    "affaire_nom": "CONSTRUCTION D'UN CENTRE D'INFORMATION",
                },
            }
        ],
    }
    search_call = api.calls[-1]
    assert str(search_call.url) == f"{SOLSCORE_API}/general/searchSitesByAreaDetails"
    assert json.loads(search_call.content) == {"bounds": PARIS}


def test_surveys_are_renamed_for_the_front_with_boolean_kind_flags(client, monkeypatch):
    simulate(monkeypatch, SimulatedSolscoreApi())

    features = search(client, "/searchSurveysByAreaDetails").json()["features"]

    assert features == [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [2.353003, 48.857975]},
            "properties": {
                "id": "IP.04.0035_sc2",
                "nom": "sc2",
                "site_uuid": "IP.04.0035",
                "has_mesure_pressiometrique": False,
                "has_essai_penetro_dynamique": True,
                "has_lithologie": True,
            },
        }
    ]


def test_survey_positions_have_no_properties(client, monkeypatch):
    api = simulate(monkeypatch, SimulatedSolscoreApi())

    features = search(client, "/searchSurveysByArea").json()["features"]

    assert features == [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [2.353003, 48.857976]}, "properties": {}}]
    assert api.calls[-1].url.path == "/general/searchSurveysByArea"


def test_sites_without_details_come_from_the_detailed_route_without_properties(client, monkeypatch):
    api = simulate(monkeypatch, SimulatedSolscoreApi())

    features = search(client, "/searchSitesByArea").json()["features"]

    assert features == [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [2.346791, 48.854536]}, "properties": {}}]
    assert api.calls[-1].url.path == "/general/searchSitesByAreaDetails"


def test_the_service_account_logs_in_once_then_reuses_its_token(client, monkeypatch):
    api = simulate(monkeypatch, SimulatedSolscoreApi())

    search(client, "/searchSitesByAreaDetails")
    search(client, "/searchSurveysByAreaDetails")

    logins = [call for call in api.calls if call.url.path == "/auth"]
    assert len(logins) == 1
    assert parse_qs(logins[0].content.decode()) == {"username": ["service"], "password": ["secret"]}


def test_an_expired_token_is_renewed_and_the_search_retried(client, monkeypatch):
    api = simulate(monkeypatch, SimulatedSolscoreApi(valid_tokens=("token-1", "token-2")))
    search(client, "/searchSitesByAreaDetails")
    api.valid_token = "token-expired"

    response = search(client, "/searchSitesByAreaDetails")

    assert response.status_code == 200
    assert response.json()["features"]
    assert api.calls[-1].headers["authorization"] == "Bearer token-2"


def test_an_area_without_data_returns_an_empty_collection(client, monkeypatch):
    simulate(monkeypatch, SimulatedSolscoreApi(answers={route: [] for route in ANSWERS}))

    response = search(client, "/searchSurveysByAreaDetails")

    assert response.status_code == 200
    assert response.json() == {"type": "FeatureCollection", "features": []}


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(httpx.ConnectError("refused"), id="unreachable"),
        pytest.param(httpx.Response(500, text="Internal Server Error"), id="server error"),
        pytest.param(httpx.Response(200, text="<html>"), id="not json"),
        pytest.param(httpx.Response(200, json={"detail": "?"}), id="not a feature collection"),
    ],
)
def test_a_failing_solscore_api_answers_502(client, monkeypatch, answer):
    def handler(request):
        if request.url.path == "/auth":
            return httpx.Response(200, json={"access_token": "token-1"})
        if isinstance(answer, Exception):
            raise answer
        return answer

    simulate(monkeypatch, handler)

    response = search(client, "/searchSurveysByAreaDetails")

    assert response.status_code == 502
    assert response.json() == {"detail": "API Solscore injoignable"}


def test_refused_service_credentials_answer_502(client, monkeypatch):
    simulate(monkeypatch, lambda request: httpx.Response(401, json={"detail": "Incorrect username or password"}))

    assert search(client, "/searchSitesByAreaDetails").status_code == 502


def test_without_solscore_api_configuration_the_map_answers_502(client, monkeypatch):
    monkeypatch.setattr(config, "solscore_api_url", None)

    assert search(client, "/searchSitesByAreaDetails").status_code == 502


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
def test_invalid_bounds_are_rejected_without_calling_the_solscore_api(client, monkeypatch, bounds):
    api = simulate(monkeypatch, SimulatedSolscoreApi())

    assert search(client, "/searchSurveysByAreaDetails", bounds).status_code == 422
    assert api.calls == []


def test_a_request_without_bounds_is_rejected(client):
    assert client.post("/searchSurveysByAreaDetails", json={}).status_code == 422


PRESSUREMETER_ONLY = {
    "type": "Feature",
    "geometry": {"type": "Point", "coordinates": [2.35, 48.85]},
    "properties": {"id": "A_sp1", "name": "sp1", "site_id": "A", "has_pressuremeter": True, "has_penetrometer": False, "has_lithology": False, "has_pz_equipment": False},
}
PZ_ONLY = {
    "type": "Feature",
    "geometry": {"type": "Point", "coordinates": [2.36, 48.86]},
    "properties": {"id": "B_pz1", "name": "pz1", "site_id": "B", "has_pressuremeter": False, "has_penetrometer": False, "has_lithology": False, "has_pz_equipment": True},
}
LITHOLOGY_ONLY = {
    "type": "Feature",
    "geometry": {"type": "Point", "coordinates": [2.34, 48.84]},
    "properties": {"id": "C_sc1", "name": "sc1", "site_id": "C", "has_pressuremeter": False, "has_penetrometer": False, "has_lithology": True, "has_pz_equipment": False},
}


def site(identifier):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [2.35, 48.85]},
        "properties": {"id": identifier, "project_id": f"p-{identifier}", "project_number": identifier, "project_description": identifier},
    }


class RecordingSolscoreApi:
    def __init__(self, answer):
        self.answer = answer
        self.searches = []

    def __call__(self, request):
        if request.url.path == "/auth":
            return httpx.Response(200, json={"access_token": "token-1"})
        body = json.loads(request.content)
        self.searches.append((request.url.path, {key: value for key, value in body.items() if key != "bounds"}))
        return httpx.Response(200, json={"type": "FeatureCollection", "features": self.answer(request.url.path, body)})


def filtered_search(client, route, filters):
    return client.post(route, json={"bounds": PARIS, "filters": filters})


def test_one_kind_one_water_level_and_one_origin_are_all_required_by_the_solscore_api(client, monkeypatch):
    api = simulate(monkeypatch, RecordingSolscoreApi(lambda path, body: [LITHOLOGY_ONLY]))

    response = filtered_search(client, "/searchSurveysByAreaDetails", {"surveyKinds": ["lithology"], "waterLevels": ["present"], "origins": ["fondasol"]})

    assert response.status_code == 200
    assert api.searches == [("/general/searchSurveysByAreaDetails", {"has_lithology": True, "has_water_levels": True, "is_survey_fondasol": True})]


def test_absent_water_levels_and_external_origin_ask_for_false_flags(client, monkeypatch):
    api = simulate(monkeypatch, RecordingSolscoreApi(lambda path, body: []))

    filtered_search(client, "/searchSurveysByArea", {"waterLevels": ["absent"], "origins": ["external"]})

    assert api.searches == [("/general/searchSurveysByArea", {"has_water_levels": False, "is_survey_fondasol": False})]


def test_both_values_of_a_section_do_not_filter(client, monkeypatch):
    api = simulate(monkeypatch, RecordingSolscoreApi(lambda path, body: []))

    filtered_search(client, "/searchSitesByAreaDetails", {"waterLevels": ["present", "absent"], "origins": ["fondasol", "external"]})

    assert api.searches == [("/general/searchSitesByAreaDetails", {})]


def test_several_survey_kinds_keep_surveys_having_any_of_them(client, monkeypatch):
    api = simulate(monkeypatch, RecordingSolscoreApi(lambda path, body: [PRESSUREMETER_ONLY, PZ_ONLY, LITHOLOGY_ONLY]))

    features = filtered_search(client, "/searchSurveysByAreaDetails", {"surveyKinds": ["pressuremeter", "pzEquipment"], "origins": ["fondasol"]}).json()["features"]

    assert [feature["properties"]["id"] for feature in features] == ["A_sp1", "B_pz1"]
    assert api.searches == [("/general/searchSurveysByAreaDetails", {"is_survey_fondasol": True})]


def test_several_survey_kinds_on_positions_read_the_details_and_return_no_properties(client, monkeypatch):
    api = simulate(monkeypatch, RecordingSolscoreApi(lambda path, body: [PRESSUREMETER_ONLY, PZ_ONLY, LITHOLOGY_ONLY]))

    features = filtered_search(client, "/searchSurveysByArea", {"surveyKinds": ["lithology", "pzEquipment"]}).json()["features"]

    assert features == [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [2.36, 48.86]}, "properties": {}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [2.34, 48.84]}, "properties": {}},
    ]
    assert api.searches == [("/general/searchSurveysByAreaDetails", {})]


def test_several_survey_kinds_on_sites_ask_each_kind_and_merge_the_sites(client, monkeypatch):
    sites_by_kind = {"has_pressuremeter": [site("A"), site("B")], "has_penetrometer": [site("B"), site("C")]}
    api = simulate(monkeypatch, RecordingSolscoreApi(lambda path, body: next(sites_by_kind[flag] for flag in sites_by_kind if body.get(flag))))

    features = filtered_search(client, "/searchSitesByAreaDetails", {"surveyKinds": ["pressuremeter", "penetrometer"], "waterLevels": ["present"]}).json()["features"]

    assert [feature["properties"]["uuid"] for feature in features] == ["A", "B", "C"]
    assert api.searches == [
        ("/general/searchSitesByAreaDetails", {"has_water_levels": True, "has_pressuremeter": True}),
        ("/general/searchSitesByAreaDetails", {"has_water_levels": True, "has_penetrometer": True}),
    ]


@pytest.mark.parametrize(
    "filters",
    [
        pytest.param({"surveyKinds": ["unknown"]}, id="unknown survey kind"),
        pytest.param({"waterLevels": ["sometimes"]}, id="unknown water level"),
        pytest.param({"origins": "fondasol"}, id="origin not in a list"),
    ],
)
def test_unknown_filters_are_rejected_without_calling_the_solscore_api(client, monkeypatch, filters):
    api = simulate(monkeypatch, SimulatedSolscoreApi())

    assert filtered_search(client, "/searchSurveysByAreaDetails", filters).status_code == 422
    assert api.calls == []
