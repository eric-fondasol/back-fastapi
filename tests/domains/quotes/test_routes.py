import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.auth import current_user
from app.core.config import config
from app.domains.quotes import sources
from app.main import app

NAV = "https://nav.test/ODataV4/Company('FONDASOL')"
SQ_31GT_26_10_025 = {
    "Document_Type": "Quote",
    "No": "SQ.31GT.26.10.025",
    "Job_No": "PR.31GT.26.0134",
    "Job_Description": "Etude hydrogéologique et de stabilité de talus",
    "Delivery_Address": "20 Rue de Montrose",
    "Delivery_Post_Code": "31240",
    "Delivery_City": "SAINT JEAN",
    "Delivery_Country_Region_Code": "FR",
    "Delivery_GPS_Longitude": 1.506608808004,
    "Delivery_GPS_Latitude": 43.660226785768,
}


@pytest.fixture(scope="module")
def client():
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def nav_configuration(monkeypatch):
    monkeypatch.setattr(config, "nav_odata_base_uri", NAV)
    monkeypatch.setattr(config, "nav_username", "API_TEST")
    monkeypatch.setattr(config, "nav_password", SecretStr("secret"))


def simulated_nav(monkeypatch, answer):
    calls = []

    def handler(request):
        calls.append(request)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(sources, "transport", httpx.MockTransport(handler))
    return calls


def test_a_quote_gives_its_project_without_the_nav_prefix_and_its_delivery_position(client, monkeypatch):
    simulated_nav(monkeypatch, httpx.Response(200, json={"value": [SQ_31GT_26_10_025]}))

    response = client.get("/quotes/SQ.31GT.26.10.025")

    assert response.status_code == 200
    assert response.json() == {
        "number": "SQ.31GT.26.10.025",
        "project_number": "31GT.26.0134",
        "description": "Etude hydrogéologique et de stabilité de talus",
        "address": "20 Rue de Montrose",
        "post_code": "31240",
        "city": "SAINT JEAN",
        "country_code": "FR",
        "position": {"longitude": 1.506608808004, "latitude": 43.660226785768},
    }


def test_nav_is_asked_for_the_exact_number_typed_in_any_case_with_basic_auth(client, monkeypatch):
    calls = simulated_nav(monkeypatch, httpx.Response(200, json={"value": [SQ_31GT_26_10_025]}))

    client.get("/quotes/ sq.31gt.26.10.025 ")

    request = calls[0]
    assert request.url.path == "/ODataV4/Company('FONDASOL')/FDS_API_Devis_RapportAutomatique"
    assert request.url.params["$filter"] == "No eq 'SQ.31GT.26.10.025'"
    assert "Job_No" in request.url.params["$select"].split(",")
    assert request.headers["authorization"] == httpx.BasicAuth("API_TEST", "secret")._auth_header


@pytest.mark.parametrize("gps", [(0, 0), (None, None), ("", "")])
def test_a_quote_without_gps_has_no_position(client, monkeypatch, gps):
    row = {**SQ_31GT_26_10_025, "Delivery_GPS_Longitude": gps[0], "Delivery_GPS_Latitude": gps[1]}
    simulated_nav(monkeypatch, httpx.Response(200, json={"value": [row]}))

    assert client.get("/quotes/SQ.31GT.26.10.025").json()["position"] is None


def test_a_quote_without_project_yet_has_no_project_number(client, monkeypatch):
    simulated_nav(monkeypatch, httpx.Response(200, json={"value": [{**SQ_31GT_26_10_025, "Job_No": ""}]}))

    assert client.get("/quotes/SQ.31GT.26.10.025").json()["project_number"] is None


def test_an_unknown_quote_answers_404(client, monkeypatch):
    simulated_nav(monkeypatch, httpx.Response(200, json={"value": []}))

    response = client.get("/quotes/SQ.00XX.26.10.999")

    assert (response.status_code, response.json()) == (404, {"detail": "Devis SQ.00XX.26.10.999 introuvable"})


@pytest.mark.parametrize("number", ["SQ' or 1 eq 1 or No eq '", "SQ 31GT", ".SQ", "S" * 41])
def test_refuses_anything_that_could_leave_the_odata_filter_before_calling_nav(client, monkeypatch, number):
    simulated_nav(monkeypatch, pytest.fail)
    monkeypatch.setattr(sources, "quote_rows", lambda number: pytest.fail("NAV appelé"))

    assert client.get(f"/quotes/{number}").status_code == 422


@pytest.mark.parametrize(
    "answer",
    [httpx.Response(401), httpx.Response(500), httpx.Response(200, text="<html>"), httpx.Response(200, json={"error": {}}), httpx.ConnectTimeout("muet")],
)
def test_nav_out_of_order_answers_502(client, monkeypatch, answer):
    simulated_nav(monkeypatch, answer)

    response = client.get("/quotes/SQ.31GT.26.10.025")

    assert (response.status_code, response.json()) == (502, {"detail": "Navision injoignable"})


def test_nav_not_configured_answers_502(client, monkeypatch):
    monkeypatch.setattr(config, "nav_password", None)
    monkeypatch.setattr(sources, "transport", httpx.MockTransport(lambda request: pytest.fail("NAV appelé")))

    assert client.get("/quotes/SQ.31GT.26.10.025").status_code == 502


def test_requires_a_token(client, monkeypatch):
    monkeypatch.delitem(app.dependency_overrides, current_user)
    monkeypatch.setattr(sources, "quote_rows", lambda number: pytest.fail("NAV appelé"))

    assert client.get("/quotes/SQ.31GT.26.10.025").status_code == 401
