import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core import solscore_api
from app.core.auth import current_user
from app.core.config import config
from app.main import app

SOLSCORE_API = "http://solscore-api.test"
LYON = {"lat": 45.7606, "lon": 4.859}
PARCEL = [[4.859, 45.76], [4.86, 45.76], [4.86, 45.761], [4.859, 45.76]]


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
    def __init__(self, answers, failing=()):
        self.answers = answers
        self.failing = set(failing)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return httpx.Response(200, json={"access_token": "service-token", "token_type": "bearer"})
        assert request.headers["authorization"] == "Bearer service-token"
        self.calls.append((request.url.path, json.loads(request.content)))
        if request.url.path in self.failing:
            return httpx.Response(500, text="Internal Server Error")
        return httpx.Response(200, json=self.answers[request.url.path])

    def body_sent_to(self, path: str) -> dict:
        return next(body for called, body in self.calls if called == path)


def simulate(monkeypatch, answers, failing=()):
    api = SimulatedSolscoreApi(answers, failing)
    monkeypatch.setattr(solscore_api, "transport", httpx.MockTransport(api))
    return api


@pytest.mark.parametrize(
    ("route", "request_body", "solscore_route"),
    [
        ("/fr/natural-hazards/natural-disasters", {**LYON, "rayon_m": 500, "code_insee": "69383"}, "/fr/catnat"),
        ("/fr/natural-hazards/cavities", {**LYON, "rayon_m": 2000, "code_insee": "69383", "nb_cavites": 5}, "/fr/cavites"),
        ("/fr/natural-hazards/risk-plans", LYON, "/fr/ppr"),
        ("/fr/natural-hazards/risk-plans", {"parcelles": [PARCEL], "rayon_m": 50}, "/fr/ppr"),
        ("/fr/urban-planning/plu", LYON, "/fr/plu"),
        ("/fr/urban-planning/plu", {"parcelles": [PARCEL], "rayon_m": 50}, "/fr/plu"),
        ("/fr/geology/formations", {**LYON, "rayon_m": 100}, "/fr/geologie"),
        ("/fr/hydrogeology/bss-works", {**LYON, "rayon_m": 500, "nb_bss": 3}, "/fr/hydrogeologie/points_bss"),
        ("/fr/hydrogeology/ades-works", LYON, "/fr/hydrogeologie/points_ades"),
        ("/fr/hydrogeology/ades-chronicles", {"code_bss": "06987A0186/S"}, "/fr/hydrogeologie/chroniques_ades"),
        ("/fr/environment/pyrotechnics", LYON, "/fr/risque_pyrotechnique"),
        ("/fr/environment/archaeological-excavations", {**LYON, "rayon_m": 2500}, "/fr/inrap"),
        ("/fr/environment/casias-sites", {**LYON, "rayon_m": 200}, "/fr/casias"),
    ],
)
def test_each_route_relays_its_body_to_the_solscore_api_and_returns_the_answer_unchanged(client, monkeypatch, route, request_body, solscore_route):
    answer = {"mode_recherche": "point", "relayed": solscore_route}
    api = simulate(monkeypatch, {solscore_route: answer})

    response = client.post(route, json=request_body)

    assert response.status_code == 200
    assert response.json() == answer
    assert api.body_sent_to(solscore_route) == request_body


def test_parcels_are_relayed_and_absent_fields_are_not_sent_as_null(client, monkeypatch):
    api = simulate(monkeypatch, {"/fr/catnat": {"catnat": []}})

    response = client.post("/fr/natural-hazards/natural-disasters", json={"parcelles": [PARCEL], "rayon_m": 500})

    assert response.status_code == 200
    assert api.body_sent_to("/fr/catnat") == {"parcelles": [PARCEL], "rayon_m": 500}


@pytest.mark.parametrize(
    ("label", "request_body"),
    [
        ("no place", {"rayon_m": 500}),
        ("latitude without longitude", {"lat": 45.76, "rayon_m": 500}),
        ("latitude out of range", {"lat": 91, "lon": 4.85, "rayon_m": 500}),
        ("oversized radius", {**LYON, "rayon_m": 50000}),
        ("missing radius", LYON),
        ("malformed INSEE code", {**LYON, "rayon_m": 500, "code_insee": "69 383"}),
        ("parcel with two vertices", {"parcelles": [PARCEL[:2]], "rayon_m": 500}),
    ],
)
def test_an_invalid_request_is_refused_without_calling_the_solscore_api(client, monkeypatch, label, request_body):
    api = simulate(monkeypatch, {})

    response = client.post("/fr/natural-hazards/natural-disasters", json=request_body)

    assert response.status_code == 422, label
    assert api.calls == []


@pytest.mark.parametrize("route", ["/fr/natural-hazards/risk-plans", "/fr/urban-planning/plu"])
def test_a_buffer_beyond_what_the_solscore_api_accepts_is_refused(client, monkeypatch, route):
    api = simulate(monkeypatch, {})

    assert client.post(route, json={**LYON, "rayon_m": 1001}).status_code == 422
    assert client.post(route, json={**LYON, "rayon_m": 0}).status_code == 422
    assert client.post(route, json={"rayon_m": 50}).status_code == 422
    assert api.calls == []


def test_a_malformed_station_code_is_refused(client, monkeypatch):
    api = simulate(monkeypatch, {})

    assert client.post("/fr/hydrogeology/ades-chronicles", json={"code_bss": "../admin"}).status_code == 422
    assert api.calls == []


def test_a_failing_solscore_api_gives_502(client, monkeypatch):
    simulate(monkeypatch, {}, failing={"/fr/hydrogeologie/points_bss"})

    response = client.post("/fr/hydrogeology/bss-works", json={**LYON, "rayon_m": 500, "nb_bss": 3})

    assert response.status_code == 502


def test_without_solscore_api_configuration_the_routes_answer_502(client, monkeypatch):
    monkeypatch.setattr(config, "solscore_api_url", None)

    assert client.post("/fr/environment/pyrotechnics", json=LYON).status_code == 502


HAZARD_ANSWERS = {
    "/fr/alea/rga": {"mode_recherche": "point", "alea_rga": {"alea_sensibilite": "Exposition moyenne"}},
    "/fr/alea/inondation": {"mode_recherche": "point", "alea_inondation": [{"libelle_zone": "Zone verte"}]},
    "/fr/alea/remontee_nappe": {"mode_recherche": "point", "alea_remnappe": {"alea_sensibilite": "Faible"}},
    "/fr/alea/mouvement_terrain": {"mode_recherche": "point", "alea_mvt": []},
    "/fr/alea/sismique": {"mode_recherche": "point", "alea_sismique": {"alea_sensibilite": "2 - FAIBLE"}},
    "/fr/alea/radon": {"alea_radon": {"alea_sensibilite": "1"}},
}


def test_the_six_natural_hazards_are_merged_into_one_answer(client, monkeypatch):
    api = simulate(monkeypatch, HAZARD_ANSWERS)

    response = client.post("/fr/natural-hazards", json={**LYON, "code_insee": "69383"})

    assert response.status_code == 200
    assert response.json() == {
        "alea_rga": {"alea_sensibilite": "Exposition moyenne"},
        "alea_inondation": [{"libelle_zone": "Zone verte"}],
        "alea_remnappe": {"alea_sensibilite": "Faible"},
        "alea_mvt": [],
        "alea_sismique": {"alea_sensibilite": "2 - FAIBLE"},
        "alea_radon": {"alea_sensibilite": "1"},
    }
    assert api.body_sent_to("/fr/alea/rga") == {**LYON, "code_insee": "69383"}
    assert api.body_sent_to("/fr/alea/inondation") == LYON
    assert api.body_sent_to("/fr/alea/mouvement_terrain") == LYON


def test_hazards_are_asked_one_after_the_other_fastest_first_because_the_solscore_api_serves_one_request_at_a_time(client, monkeypatch):
    api = simulate(monkeypatch, HAZARD_ANSWERS)

    client.post("/fr/natural-hazards", json={**LYON, "code_insee": "69383"})

    assert [path for path, _ in api.calls] == [
        "/fr/alea/rga",
        "/fr/alea/sismique",
        "/fr/alea/radon",
        "/fr/alea/remontee_nappe",
        "/fr/alea/inondation",
        "/fr/alea/mouvement_terrain",
    ]


def test_a_failing_hazard_is_left_out(client, monkeypatch):
    simulate(monkeypatch, HAZARD_ANSWERS, failing={"/fr/alea/remontee_nappe"})

    response = client.post("/fr/natural-hazards", json={**LYON, "code_insee": "69383"})

    assert response.status_code == 200
    assert "alea_remnappe" not in response.json()
    assert response.json()["alea_rga"] == {"alea_sensibilite": "Exposition moyenne"}


def test_no_hazard_answering_gives_502(client, monkeypatch):
    simulate(monkeypatch, HAZARD_ANSWERS, failing=set(HAZARD_ANSWERS))

    assert client.post("/fr/natural-hazards", json=LYON).status_code == 502
