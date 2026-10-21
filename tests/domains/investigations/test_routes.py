from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.auth import Identity, current_identity
from app.core.profile import current_profile
from app.domains.investigations import services
from app.main import app

SPIKE = Identity("spike@fondasol.fr", "6f1c2a3e-0b1d-4c55-9a77-1f2e3d4c5b6a", "Spike Test")
OTHER = Identity("autre@fondasol.fr", "7a2d3b4f-1c2e-4d66-8b88-2a3f4e5d6c7b", "Autre Test")
UNKNOWN_UUID = "c3b8a526-c399-4c9e-86dc-5cafcf9595a2"


@pytest.fixture
def client(refonte_database):
    caller = {"identity": SPIKE}
    app.dependency_overrides[current_identity] = lambda: caller["identity"]

    with TestClient(app) as test_client:
        test_client.caller = caller
        yield test_client

    app.dependency_overrides.clear()


def send(client, method, path, body=None, identity=SPIKE, expected=200):
    client.caller["identity"] = identity
    response = client.request(method, path, json=body)
    assert response.status_code == expected, response.text
    return response.json()


def create(client, body, identity=SPIKE):
    return send(client, "POST", "/investigations", body, identity, 201)


def scalar(engine, sql, **parameters):
    with engine.connect() as connection:
        return connection.execute(text(sql), parameters).scalar()


def test_a_first_save_creates_the_investigation_and_its_version_1_in_the_user_name(client, refonte_database):
    created = create(client, {"projectRef": "63GT.24.0048", "name": "RD613", "data": '{"etape":1}', "comment": "Premier jet"})

    assert [created["projectRef"], created["name"], created["version"]["version"], created["version"]["comment"]] == [
        "63GT.24.0048", "RD613", 1, "Premier jet",
    ]
    assert created["version"]["author"] == {
        "id": str(scalar(refonte_database, "SELECT id FROM users WHERE email = 'spike@fondasol.fr'")),
        "name": "Spike Test",
    }
    assert (created["latestVersion"], created["hasCoordinates"]) == (1, False)
    assert created["version"]["createdAt"].endswith("+00:00")
    assert "data" not in created["version"]
    assert send(client, "GET", f"/investigations/{created['uuid']}")["version"]["data"] == '{"etape":1}'


def test_a_new_version_leaves_the_previous_one_untouched(client):
    page_uuid = create(client, {"projectRef": "63GT.24.0048", "data": "v1"})["uuid"]

    second = send(client, "POST", f"/investigations/{page_uuid}/versions", {"data": "v2", "comment": "Rayon élargi"}, OTHER, 201)

    assert [second["version"]["version"], second["version"]["author"]["name"]] == [2, "Autre Test"]
    first = send(client, "GET", f"/investigations/{page_uuid}/versions/1")
    assert [first["version"]["data"], first["latestVersion"]] == ["v1", 2]
    assert send(client, "GET", f"/investigations/{page_uuid}")["version"]["data"] == "v2"


def test_overwriting_the_latest_version_keeps_its_number(client, refonte_database):
    page_uuid = create(client, {"projectRef": "63GT.24.0048", "data": "v1"})["uuid"]
    send(client, "POST", f"/investigations/{page_uuid}/versions", {"data": "v2"}, expected=201)

    revised = send(client, "PUT", f"/investigations/{page_uuid}/versions/2", {"data": "v2 corrigée", "comment": "Faute"})

    assert [revised["version"]["version"], revised["version"]["comment"]] == [2, "Faute"]
    assert send(client, "GET", f"/investigations/{page_uuid}")["version"]["data"] == "v2 corrigée"
    assert scalar(refonte_database, "SELECT count(*) FROM saved_page_versions") == 2


def test_an_earlier_version_cannot_be_overwritten(client):
    page_uuid = create(client, {"projectRef": "63GT.24.0048", "data": "v1"})["uuid"]
    send(client, "POST", f"/investigations/{page_uuid}/versions", {"data": "v2"}, expected=201)

    refusal = send(client, "PUT", f"/investigations/{page_uuid}/versions/1", {"data": "réécrite"}, expected=409)

    assert "V2" in refusal["errors"]
    assert send(client, "GET", f"/investigations/{page_uuid}/versions/1")["version"]["data"] == "v1"


def test_each_investigation_of_a_project_numbers_its_own_versions(client):
    rd613 = create(client, {"projectRef": "PR.34GT.26.0057", "name": "RD613", "data": "a"})["uuid"]
    create(client, {"projectRef": "PR.34GT.26.0057", "name": "La Bourbou", "data": "b"})
    create(client, {"projectRef": "PR.34GT.26.0058", "name": "Ailleurs", "data": "c"})
    send(client, "POST", f"/investigations/{rd613}/versions", {"data": "a2"}, expected=201)

    investigations = send(client, "GET", "/investigations?projectRef=PR.34GT.26.0057")

    assert [[item["name"], [version["version"] for version in item["versions"]]] for item in investigations] == [
        ["RD613", [2, 1]],
        ["La Bourbou", [1]],
    ]
    assert "data" not in investigations[0]["versions"][0]


def test_renaming_an_investigation_applies_to_all_its_versions(client):
    page_uuid = create(client, {"projectRef": "63GT.24.0048", "name": "Ancien nom", "data": "v1"})["uuid"]

    renamed = send(client, "PATCH", f"/investigations/{page_uuid}", {"name": "RD613"})

    assert renamed == {"uuid": page_uuid, "projectRef": "63GT.24.0048", "name": "RD613", "hasCoordinates": False}
    assert send(client, "GET", f"/investigations/{page_uuid}/versions/1")["name"] == "RD613"


@pytest.mark.parametrize(
    "body",
    [
        {"projectRef": "63GT.24.0048", "data": "  "},
        {"data": "v1"},
        {"projectRef": "63GT.24.0048", "data": "v1", "comment": "x" * 2001},
        {"projectRef": "x" * 101, "data": "v1"},
        {"projectRef": "63GT.24.0048", "data": "v1", "name": 12},
    ],
    ids=["blank content", "no project", "comment too long", "project too long", "name not a string"],
)
def test_an_incomplete_save_is_refused(client, refonte_database, body):
    send(client, "POST", "/investigations", body, expected=400)

    assert scalar(refonte_database, "SELECT count(*) FROM saved_pages") == 0


def test_content_sent_as_an_object_is_stored_as_json_text(client):
    page_uuid = create(client, {"projectRef": "63GT.24.0048", "data": {"coordinates": {"lat": 43.6, "lng": 1.4}, "nom": "Été"}})["uuid"]

    latest = send(client, "GET", f"/investigations/{page_uuid}")

    assert latest["version"]["data"] == '{"coordinates":{"lat":43.6,"lng":1.4},"nom":"Été"}'
    assert latest["hasCoordinates"] is True


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"/investigations/{UNKNOWN_UUID}"),
        ("GET", "/investigations/{uuid}/versions/5"),
        ("PUT", "/investigations/{uuid}/versions/5"),
        ("POST", f"/investigations/{UNKNOWN_UUID}/versions"),
        ("PATCH", f"/investigations/{UNKNOWN_UUID}"),
        ("GET", "/investigations/pas-un-uuid"),
        ("GET", "/investigations/------------------------------------"),
        ("GET", "/investigations/{uuid}/versions/deux"),
    ],
)
def test_an_unknown_investigation_or_version_answers_not_found(client, method, path):
    page_uuid = create(client, {"projectRef": "63GT.24.0048", "data": "v1"})["uuid"]

    send(client, method, path.format(uuid=page_uuid), {"data": "x"} if method != "GET" else None, expected=404)


def test_the_project_reference_is_required_to_list_investigations(client):
    send(client, "GET", "/investigations?projectRef=%20", expected=400)


def test_deleting_an_account_keeps_its_versions_and_the_author_name(client, refonte_database):
    page_uuid = create(client, {"projectRef": "63GT.24.0048", "data": "v1"})["uuid"]

    with refonte_database.begin() as connection:
        connection.execute(text("DELETE FROM users WHERE email = 'spike@fondasol.fr'"))

    assert send(client, "GET", f"/investigations/{page_uuid}")["version"]["author"] == {"id": None, "name": "Spike Test"}


def test_saved_pages_data_always_follows_the_latest_version(client, refonte_database):
    page_uuid = create(client, {"projectRef": "63GT.24.0048", "data": "v1"})["uuid"]
    send(client, "POST", f"/investigations/{page_uuid}/versions", {"data": "v2"}, expected=201)
    send(client, "PUT", f"/investigations/{page_uuid}/versions/2", {"data": "v2 bis"})

    assert scalar(refonte_database, "SELECT data FROM saved_pages WHERE uuid = :uuid", uuid=page_uuid) == "v2 bis"
    assert scalar(refonte_database, "SELECT email FROM saved_pages WHERE uuid = :uuid", uuid=page_uuid) == "spike@fondasol.fr"


def test_simultaneous_saves_never_share_a_version_number(client, refonte_database):
    page_uuid = create(client, {"projectRef": "63GT.24.0048", "data": "v1"})["uuid"]
    profile = current_profile(SPIKE)

    with ThreadPoolExecutor(max_workers=6) as pool:
        saved = list(pool.map(lambda index: services.add_version(profile, page_uuid, f"v{index}", None)[1].number, range(12)))

    assert sorted(saved) == list(range(2, 14))
    assert scalar(refonte_database, "SELECT max(version) FROM saved_page_versions") == 13


@pytest.fixture
def pages(client):
    for project_ref, data in [
        ("Bellecour", "{}"),
        ("Avec position", '{"coordinates":{"lng":1,"lat":2}}'),
        ("Sans position", '{"coordinates":null}'),
        ("Remise 100 % conforme", "{}"),
    ]:
        create(client, {"projectRef": project_ref, "data": data})


def test_the_search_finds_by_project_without_case(client, pages):
    found = send(client, "GET", "/saved-page/search?q=belle")

    assert [item["projectRef"] for item in found] == ["Bellecour"]


def test_the_search_uses_lowercase_keys_and_flags_the_position(client, pages):
    found = {item["projectRef"]: item for item in send(client, "GET", "/saved-page/search")}

    assert list(found["Avec position"]) == ["uuid", "projectRef", "projectRefCommentaire", "hasCoordinates"]
    assert (found["Avec position"]["hasCoordinates"], found["Sans position"]["hasCoordinates"]) == (True, False)


def test_a_wildcard_is_searched_literally(client, pages):
    assert [item["projectRef"] for item in send(client, "GET", "/saved-page/search?q=%25")] == ["Remise 100 % conforme"]


def test_the_search_is_limited(client, pages):
    assert len(send(client, "GET", "/saved-page/search?limit=2")) == 2
    assert len(send(client, "GET", "/saved-page/search?limit=0")) == 4


def test_a_search_without_result_answers_not_found(client, pages):
    assert send(client, "GET", "/saved-page/search?q=introuvable", expected=404) == {"message": "Aucun SavedPage trouve"}


def test_a_request_without_token_is_refused(client):
    app.dependency_overrides.clear()

    assert client.get("/investigations?projectRef=A").status_code == 401
    assert client.get("/saved-page/search").status_code == 401
