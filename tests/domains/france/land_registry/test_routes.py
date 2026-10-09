import pytest
from fastapi.testclient import TestClient

from app.core.auth import current_user
from app.domains.france.land_registry import sources
from app.main import app
from tests.domains.france.land_registry.test_services import SORGUES_AB_0004

ROUTE = "/fr/land-registry/parcels"
BODY = {"code_insee": "84129", "section": "AB", "parcelle": "4", "com_abs": "000"}


@pytest.fixture(scope="module")
def client():
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_a_known_parcel_is_returned_as_geojson_with_its_properties(client, monkeypatch):
    calls = []
    monkeypatch.setattr(sources, "parcel_features", lambda reference: calls.append(reference) or [SORGUES_AB_0004])

    response = client.post(ROUTE, json=BODY)

    assert response.status_code == 200
    assert calls[0].idu == "84129000AB0004"
    feature = response.json()["features"][0]
    assert feature["geometry"]["type"] == "MultiPolygon"
    assert {key: feature["properties"][key] for key in ("idu", "nom_com", "section", "numero", "contenance")} == {
        "idu": "84129000AB0004",
        "nom_com": "Sorgues",
        "section": "AB",
        "numero": "0004",
        "contenance": 5070,
    }


def test_an_unknown_parcel_answers_404_with_its_full_reference(client, monkeypatch):
    monkeypatch.setattr(sources, "parcel_features", lambda reference: [])

    response = client.post(ROUTE, json={**BODY, "parcelle": "0123"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Parcelle 84129000AB0123 introuvable"}


def test_an_unreachable_land_registry_answers_502(client, monkeypatch):
    def unavailable(reference):
        raise sources.LandRegistryUnavailable("timeout")

    monkeypatch.setattr(sources, "parcel_features", unavailable)

    assert client.post(ROUTE, json=BODY).status_code == 502


@pytest.mark.parametrize(
    "body",
    [
        {**BODY, "code_insee": "8412"},
        {**BODY, "section": "ABC"},
        {**BODY, "parcelle": "12345"},
        {**BODY, "com_abs": "abcd"},
        {"section": "AB", "parcelle": "4"},
    ],
)
def test_an_invalid_reference_is_rejected_without_calling_the_land_registry(client, monkeypatch, body):
    monkeypatch.setattr(sources, "parcel_features", lambda reference: pytest.fail("appel inattendu"))

    assert client.post(ROUTE, json=body).status_code == 422


def test_the_route_requires_a_token(client, monkeypatch):
    monkeypatch.setattr(sources, "parcel_features", lambda reference: pytest.fail("appel inattendu"))
    monkeypatch.delitem(app.dependency_overrides, current_user)

    assert client.post(ROUTE, json=BODY).status_code == 401
