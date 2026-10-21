import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.auth import Identity, current_identity
from app.main import app

SPIKE = Identity("spike@fondasol.fr", "6f1c2a3e-0b1d-4c55-9a77-1f2e3d4c5b6a", "Spike Test")
OTHER = Identity("autre@fondasol.fr", "7a2d3b4f-1c2e-4d66-8b88-2a3f4e5d6c7b", "Autre Test")
EMPTY_FAVORITES = {"projects": [], "layers": [], "addresses": []}


@pytest.fixture
def client(refonte_database):
    with refonte_database.begin() as connection:
        connection.execute(text("INSERT INTO projects (id, is_doc_ged) VALUES ('IP.02.0222', false)"))

    caller = {"identity": SPIKE}
    app.dependency_overrides[current_identity] = lambda: caller["identity"]

    with TestClient(app) as test_client:
        test_client.caller = caller
        yield test_client

    app.dependency_overrides.clear()


def call(client, method, path, body=None, identity=SPIKE):
    client.caller["identity"] = identity
    return client.request(method, path, json=body)


def address(external_id):
    return {
        "externalId": external_id,
        "label": "10 Rue de Rivoli, 75004 Paris",
        "name": "10 Rue de Rivoli",
        "context": "75004 Paris",
        "kind": "address",
        "longitude": 2.3555,
        "latitude": 48.8556,
    }


def count(engine, table):
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def test_the_profile_is_created_on_the_first_request_then_reused(client, refonte_database):
    first = call(client, "GET", "/me")
    second = call(client, "GET", "/me").json()

    assert first.status_code == 200
    assert (first.json()["email"], first.json()["displayName"]) == ("spike@fondasol.fr", "Spike Test")
    assert first.json()["id"] == second["id"]
    assert count(refonte_database, "users") == 1


def test_a_user_imported_by_email_gets_their_oid_at_sign_in(client, refonte_database):
    imported = "11111111-1111-4111-8111-111111111111"
    with refonte_database.begin() as connection:
        connection.execute(text(f"INSERT INTO users (id, email, created_at) VALUES ('{imported}', 'spike@fondasol.fr', now())"))

    assert call(client, "GET", "/me").json()["id"] == imported
    with refonte_database.connect() as connection:
        assert str(connection.execute(text("SELECT azure_oid FROM users")).scalar_one()) == SPIKE.azure_oid


def test_default_preferences_are_empty_and_extra_is_an_object(client):
    expected = {"locale": None, "theme": None, "defaultTerritory": None, "mapStyle": None, "mapLayers": [], "extra": {}}

    assert call(client, "GET", "/me/preferences").json() == expected
    assert '"extra":{}' in call(client, "PATCH", "/me/preferences", {"theme": "dark"}).text
    assert '"extra":{}' in call(client, "POST", "/me/favorites/import", []).text


def test_a_patch_only_changes_the_preferences_sent(client):
    call(client, "PATCH", "/me/preferences", {"theme": "dark", "mapLayers": [
        {"layerId": "fr-cadastre-etalab", "visible": True, "opacity": 0.8},
        {"layerId": "fr-geologie", "visible": False, "opacity": 1},
    ]})
    call(client, "PATCH", "/me/preferences", {"locale": "en"})

    preferences = call(client, "GET", "/me/preferences").json()

    assert (preferences["theme"], preferences["locale"]) == ("dark", "en")
    assert preferences["mapLayers"] == [
        {"layerId": "fr-cadastre-etalab", "visible": True, "opacity": 0.8},
        {"layerId": "fr-geologie", "visible": False, "opacity": 1},
    ]


def test_an_invalid_preference_is_refused_without_saving_anything(client):
    response = call(client, "PATCH", "/me/preferences", {"theme": "sepia"})

    assert response.status_code == 400
    assert "theme" in response.json()["errors"]
    assert call(client, "GET", "/me/preferences").json()["theme"] is None


@pytest.mark.parametrize(("body", "message"), [("pas du json", "Corps JSON invalide."), ("[1, 2]", "Le corps doit etre un objet JSON.")])
def test_a_body_that_is_not_a_json_object_is_refused(client, body, message):
    client.caller["identity"] = SPIKE
    response = client.patch("/me/preferences", content=body, headers={"Content-Type": "application/json"})

    assert (response.status_code, response.json()) == (400, {"errors": message})


def test_a_project_and_a_layer_are_added_to_and_removed_from_favorites(client):
    assert call(client, "PUT", "/me/favorites/projects/IP.02.0222").status_code == 204
    call(client, "PUT", "/me/favorites/projects/IP.02.0222")
    call(client, "PUT", "/me/favorites/layers/fr-cadastre-etalab")

    favorites = call(client, "GET", "/me/favorites").json()
    assert (favorites["projects"], favorites["layers"]) == (["IP.02.0222"], ["fr-cadastre-etalab"])

    assert call(client, "DELETE", "/me/favorites/projects/IP.02.0222").status_code == 204
    assert call(client, "DELETE", "/me/favorites/layers/fr-cadastre-etalab").status_code == 204
    assert call(client, "GET", "/me/favorites").json() == EMPTY_FAVORITES


def test_a_project_number_with_a_slash_can_be_a_favorite(client, refonte_database):
    with refonte_database.begin() as connection:
        connection.execute(text("INSERT INTO projects (id, is_doc_ged) VALUES ('PR.GT01.25.0082 / DE-16511', false)"))

    assert call(client, "PUT", "/me/favorites/projects/PR.GT01.25.0082%20%2F%20DE-16511").status_code == 204
    assert call(client, "GET", "/me/favorites").json()["projects"] == ["PR.GT01.25.0082 / DE-16511"]


def test_an_unknown_project_cannot_be_a_favorite(client):
    response = call(client, "PUT", "/me/favorites/projects/INCONNUE")

    assert (response.status_code, response.json()) == (404, {"errors": "Affaire introuvable : INCONNUE"})


def test_an_invalid_layer_identifier_is_refused(client):
    response = call(client, "PUT", "/me/favorites/layers/-x")

    assert (response.status_code, response.json()) == (400, {"errors": "Identifiant de couche invalide."})


def test_a_favorite_address_is_created_once_per_geocoder_identifier(client):
    created = call(client, "POST", "/me/favorites/addresses", address("address.1"))
    again = call(client, "POST", "/me/favorites/addresses", address("address.1"))

    assert (created.status_code, again.status_code) == (201, 200)
    assert created.json()["id"] == again.json()["id"]
    assert created.json()["createdAt"] == again.json()["createdAt"]
    addresses = call(client, "GET", "/me/favorites").json()["addresses"]
    assert len(addresses) == 1
    assert (addresses[0]["label"], addresses[0]["name"]) == ("10 Rue de Rivoli, 75004 Paris", "10 Rue de Rivoli")
    assert (addresses[0]["longitude"], addresses[0]["latitude"]) == pytest.approx((2.3555, 48.8556))
    assert addresses[0]["createdAt"].endswith("+00:00")


def test_the_twenty_first_favorite_address_is_refused(client):
    for index in range(1, 21):
        call(client, "POST", "/me/favorites/addresses", address(f"address.{index}"))

    response = call(client, "POST", "/me/favorites/addresses", address("address.21"))

    assert (response.status_code, response.json()) == (422, {"errors": "20 adresses favorites au plus."})
    assert len(call(client, "GET", "/me/favorites").json()["addresses"]) == 20


def test_an_address_without_coordinates_is_refused(client):
    response = call(client, "POST", "/me/favorites/addresses", {"externalId": "address.1", "label": "Paris"})

    assert (response.status_code, response.json()) == (400, {"errors": "longitude et latitude sont requises."})


def test_a_user_neither_sees_nor_removes_the_favorites_of_another(client):
    call(client, "PUT", "/me/favorites/projects/IP.02.0222")
    created = call(client, "POST", "/me/favorites/addresses", address("address.1")).json()
    call(client, "PATCH", "/me/preferences", {"theme": "dark"})

    assert call(client, "GET", "/me/favorites", identity=OTHER).json() == EMPTY_FAVORITES
    assert call(client, "GET", "/me/preferences", identity=OTHER).json()["theme"] is None
    assert call(client, "DELETE", f"/me/favorites/addresses/{created['id']}", identity=OTHER).status_code == 404

    favorites = call(client, "GET", "/me/favorites").json()
    assert (len(favorites["addresses"]), favorites["projects"]) == (1, ["IP.02.0222"])


@pytest.mark.parametrize("address_id", [str(uuid.uuid4()), "pas-un-uuid"])
def test_removing_an_unknown_address_answers_not_found(client, address_id):
    response = call(client, "DELETE", f"/me/favorites/addresses/{address_id}")

    assert (response.status_code, response.json()) == (404, {"errors": f"Adresse favorite introuvable : {address_id}"})


def test_the_import_merges_without_duplicate_or_overwrite(client):
    call(client, "POST", "/me/favorites/addresses", address("address.1"))
    call(client, "PATCH", "/me/preferences", {"mapLayers": [{"layerId": "fr-geologie", "visible": True, "opacity": 1}]})

    response = call(client, "POST", "/me/favorites/import", {
        "addresses": [address("address.1"), address("address.2")],
        "layers": ["fr-cadastre-etalab", "fr-cadastre-etalab"],
        "mapLayers": [{"layerId": "fr-cadastre-etalab", "visible": True, "opacity": 0.5}],
    })

    assert response.status_code == 200
    result = response.json()
    assert sorted(item["externalId"] for item in result["favorites"]["addresses"]) == ["address.1", "address.2"]
    assert result["favorites"]["layers"] == ["fr-cadastre-etalab"]
    assert result["preferences"]["mapLayers"][0]["layerId"] == "fr-geologie"


def test_the_import_fills_my_layers_when_they_are_empty(client):
    result = call(client, "POST", "/me/favorites/import", {
        "mapLayers": [{"layerId": "fr-cadastre-etalab", "visible": False, "opacity": 0.5}],
    }).json()

    assert result["preferences"]["mapLayers"] == [{"layerId": "fr-cadastre-etalab", "visible": False, "opacity": 0.5}]


def test_the_import_stops_at_twenty_addresses(client):
    for index in range(1, 20):
        call(client, "POST", "/me/favorites/addresses", address(f"address.{index}"))

    result = call(client, "POST", "/me/favorites/import", {"addresses": [address("address.20"), address("address.21")]}).json()

    assert len(result["favorites"]["addresses"]) == 20


def test_an_invalid_import_saves_nothing(client):
    response = call(client, "POST", "/me/favorites/import", {
        "addresses": [address("address.1"), {"externalId": "address.2"}],
        "layers": ["fr-cadastre-etalab"],
    })

    assert response.status_code == 400
    assert call(client, "GET", "/me/favorites").json() == EMPTY_FAVORITES


def test_a_request_without_token_is_refused(client):
    app.dependency_overrides.clear()

    assert client.get("/me/favorites").status_code == 401
