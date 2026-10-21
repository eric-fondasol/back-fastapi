import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.auth import current_user
from app.core.config import config
from app.core.errors import Forbidden
from app.domains.desk_study import entities, sources
from app.domains.desk_study.entities import PlancheStatus, coordinate_text, trusted_infoterre_url
from app.main import app

FICHE = "http://ficheinfoterre.brgm.fr/InfoterreFiche/ficheBss.action?id=BSS002DRFB"


@pytest.fixture(autouse=True)
def planche_sources(monkeypatch):
    monkeypatch.setattr(config, "georisques_base_uri", "https://georisques.test/api/v1")
    monkeypatch.setattr(config, "planches_apisolscore_base_uri", "https://apisolscore.test")


@pytest.fixture
def client():
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def simulate(monkeypatch, handler):
    calls = []

    def recording(request):
        calls.append(str(request.url))
        return handler(request)

    monkeypatch.setattr(sources, "transport", httpx.MockTransport(recording))
    return calls


@pytest.mark.parametrize("url", [FICHE, "https://INFOTERRE.brgm.fr/viewer"])
def test_brgm_hosts_are_accepted_whatever_the_case(url):
    assert trusted_infoterre_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/metadata/identity/oauth2/token",
        "https://vm-azu-talend:8000/affaires/69GT.21.0142",
        "http://localhost:5432/",
        "file:///etc/passwd",
        "https://infoterre.brgm.fr.exemple.fr/",
        "https://interne.brgm.fr/",
        "pas une url",
    ],
    ids=["host metadata service", "internal GED", "database", "local file", "lookalike host", "unlisted subdomain", "unreadable"],
)
def test_any_other_address_is_refused(url):
    with pytest.raises(Forbidden):
        trusted_infoterre_url(url)


def test_a_brgm_sheet_is_relayed_with_its_type_and_neutralised(client, monkeypatch):
    calls = simulate(monkeypatch, lambda request: httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=b"<html>BSS</html>"))

    response = client.get("/infoterre", params={"infoterreUrl": FICHE})

    assert (response.status_code, response.content, calls) == (200, b"<html>BSS</html>", [FICHE])
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox; default-src 'none'"


def test_an_internal_address_is_refused_without_being_called(client, monkeypatch):
    calls = simulate(monkeypatch, lambda request: httpx.Response(200))

    response = client.get("/infoterre", params={"infoterreUrl": "http://169.254.169.254/"})

    assert (response.status_code, calls) == (403, [])
    assert response.json() == {"message": "Hote non autorise : 169.254.169.254."}


def test_a_missing_parameter_is_refused(client):
    response = client.get("/infoterre")

    assert (response.status_code, response.json()) == (400, "No infoterreUrl param")


def test_an_unreachable_brgm_answers_502(client, monkeypatch):
    def unreachable(request):
        raise httpx.ConnectError("refused")

    simulate(monkeypatch, unreachable)

    assert client.get("/infoterre", params={"infoterreUrl": FICHE}).status_code == 502


def test_a_usable_planche_carries_its_data_and_a_failed_one_its_reason():
    assert entities.ok("catnat", [1], 0.1234).to_json() == {"status": "ok", "data": [1], "elapsedMs": 123, "fromCache": False}
    assert entities.degraded("catnat", "timeout", 0.5).to_json() == {"status": "degraded", "reason": "timeout", "elapsedMs": 500, "fromCache": False}
    assert not entities.unavailable("x", "planche inconnue", 0).usable


@pytest.mark.parametrize(("value", "expected"), [(2.0, "2"), (2.3522, "2.3522"), (-0.5, "-0.5")])
def test_coordinates_are_written_like_php(value, expected):
    assert coordinate_text(value) == expected


def test_the_catalogue_lists_the_planches(client):
    assert client.get("/api/enquetes/planches").json()["planches"][:3] == ["catnat", "ppr", "geol"]


def test_all_usable_planches_answer_200_with_their_data(client, monkeypatch):
    calls = simulate(monkeypatch, lambda request: httpx.Response(200, json={"source": request.url.host}))

    response = client.post("/api/enquetes/planches", json={"longitude": 2, "latitude": 48.85, "codeInsee": "75056", "planches": ["catnat", "radon"]})

    assert response.status_code == 200
    assert response.json()["position"] == {"longitude": 2.0, "latitude": 48.85}
    assert response.json()["planches"]["catnat"]["data"] == {"source": "apisolscore.test"}
    assert sorted(calls) == [
        "https://apisolscore.test/fr/catnat?lat=48.85&lon=2&rayon=1000",
        "https://georisques.test/api/v1/radon?rayon=1000&code_insee=75056&page=1&page_size=10",
    ]


def test_failed_planches_are_reported_with_207(client, monkeypatch):
    answers = {"/fr/catnat": httpx.Response(429), "/fr/ppr": httpx.Response(500), "/fr/geol": httpx.Response(200, content=b"<html>")}
    simulate(monkeypatch, lambda request: answers[request.url.path])

    response = client.post("/api/enquetes/planches", json={"longitude": 2.35, "latitude": 48.85, "planches": ["catnat", "ppr", "geol", "inconnue"]})
    planches = response.json()["planches"]

    assert response.status_code == 207
    assert [planches[name]["status"] for name in ["catnat", "ppr", "geol", "inconnue"]] == ["degraded", "degraded", "degraded", "unavailable"]
    assert (planches["catnat"]["reason"], planches["ppr"]["reason"], planches["inconnue"]["reason"]) == ("upstream_429", "upstream_500", "planche inconnue")


def test_a_planche_without_configured_source_is_unavailable(client, monkeypatch):
    monkeypatch.setattr(config, "planches_apisolscore_base_uri", None)
    simulate(monkeypatch, lambda request: httpx.Response(200, json={}))

    planches = client.post("/api/enquetes/planches", json={"longitude": 2.35, "latitude": 48.85, "planches": ["catnat"]}).json()["planches"]

    assert planches["catnat"] == {"status": "unavailable", "reason": "source non configuree", "elapsedMs": 0, "fromCache": False}


@pytest.mark.parametrize("body", [{"latitude": 48.85}, {"longitude": 2.35}], ids=["no longitude", "no latitude"])
def test_a_position_is_required(client, body):
    response = client.post("/api/enquetes/planches", json=body)

    assert (response.status_code, response.json()) == (400, {"error": "longitude et latitude sont requis"})


def slow_transport(delay):
    async def handler(request):
        await asyncio.sleep(delay)
        return httpx.Response(200, json={})

    return httpx.MockTransport(handler)


def test_the_fan_out_is_concurrent_not_sequential(monkeypatch):
    monkeypatch.setattr(sources, "transport", slow_transport(0.4))
    started = time.perf_counter()

    results = asyncio.run(sources.fetch_planches(["catnat", "ppr", "geol", "cavites", "bss"], 2.35, 48.85, None))

    assert all(result.status is PlancheStatus.OK for result in results.values())
    assert time.perf_counter() - started < 1.2


def test_a_too_slow_planche_is_degraded_by_its_timeout(monkeypatch):
    monkeypatch.setitem(sources.CATALOGUE, "catnat", ("apisolscore", "/fr/catnat", 0.1))

    async def handler(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={})

    monkeypatch.setattr(sources, "transport", httpx.MockTransport(handler))

    results = asyncio.run(sources.fetch_planches(["catnat"], 2.35, 48.85, None))

    assert (results["catnat"].status, results["catnat"].reason) == (PlancheStatus.DEGRADED, "timeout")


def test_planches_still_pending_after_the_global_budget_are_abandoned(monkeypatch):
    monkeypatch.setattr(sources, "GLOBAL_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(sources, "transport", slow_transport(2))

    results = asyncio.run(sources.fetch_planches(["catnat"], 2.35, 48.85, None))

    assert (results["catnat"].status, results["catnat"].reason) == (PlancheStatus.DEGRADED, "aucune reponse")
