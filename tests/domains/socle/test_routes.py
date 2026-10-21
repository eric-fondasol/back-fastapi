import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.auth import current_user
from app.core.config import config
from app.domains.socle.entities import Agency, allows
from app.main import app

AGENT = "spike@fondasol.fr"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


@pytest.fixture
def client(refonte_database, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "waiting_images_dir", str(tmp_path / "waitingImages"))
    app.dependency_overrides[current_user] = lambda: AGENT

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def execute(engine, sql):
    with engine.begin() as connection:
        connection.execute(text(sql))


def scalar(engine, sql):
    with engine.connect() as connection:
        return connection.execute(text(sql)).scalar()


def test_the_latest_setting_is_returned(client, refonte_database):
    execute(
        refonte_database,
        "INSERT INTO parametrages (email, message, url_manuel_utilisateur, horodatage) VALUES "
        "('a@fondasol.fr', 'Ancien', 'https://old', '2026-01-01T00:00:00Z'), ('b@fondasol.fr', 'Bienvenue', 'https://manuel', '2026-10-01T08:30:00Z')",
    )

    assert client.get("/parametrage").json() == {
        "Email": "b@fondasol.fr",
        "Message": "Bienvenue",
        "Horodatage": "2026-10-01T08:30:00+00:00",
        "UrlManuelUtilisateur": "https://manuel",
    }


def test_a_missing_setting_gives_an_empty_structure(client):
    assert client.get("/parametrage").json() == {"Email": "", "Message": "", "Horodatage": None, "UrlManuelUtilisateur": ""}


def test_access_limited_zones_keep_the_legacy_case_and_may_be_empty(client, refonte_database):
    assert client.get("/access-limited-zones").json() == []

    execute(refonte_database, "INSERT INTO access_limited_zones (id, description, latitude, longitude, zone_km) VALUES ('Z1', 'Base aérienne', 43.6, 1.4, 2.5)")

    assert client.get("/access-limited-zones").json() == [
        {"ID": "Z1", "Description": "Base aérienne", "Latitude": 43.6, "Longitude": 1.4, "ZoneKm": 2.5}
    ]


def test_about_returns_the_caller_identity(client):
    assert client.get("/about").json() == AGENT


def test_a_visit_is_attached_to_the_agent_service(client, refonte_database):
    execute(refonte_database, f"INSERT INTO email_services (id, service_code) VALUES ('{AGENT.upper()}', '69GT')")

    visit = client.put("/ajout-statistique-visite", json={"Libelle": "openMap"}).json()

    assert (visit["Libelle"], visit["ServiceCode"], visit["UserEmail"]) == ("openMap", "69GT", AGENT)
    assert visit["Horodatage"].endswith("+00:00")
    assert scalar(refonte_database, "SELECT service_code FROM statistique_visites") == "69GT"


def test_a_visit_without_known_service_is_still_recorded(client, refonte_database):
    assert client.put("/ajout-statistique-visite", json={"Libelle": "openMap"}).json()["ServiceCode"] == ""
    assert scalar(refonte_database, "SELECT count(*) FROM statistique_visites") == 1


def test_a_visit_without_label_is_refused(client):
    response = client.put("/ajout-statistique-visite", json={})

    assert (response.status_code, response.json()) == (400, {"errors": "Libelle absent."})


@pytest.fixture
def agencies(refonte_database):
    execute(
        refonte_database,
        "INSERT INTO services (id, libelle, full_access, tab) VALUES "
        "('69GT', 'Agence de Lyon', false, 1), ('31GT', 'Agence de Toulouse', false, 2), "
        "('00GT', 'Direction technique', true, 3), ('34GT', 'Agence de Montpellier', false, 4)",
    )
    execute(refonte_database, "INSERT INTO departments (id, libelle, code_service) VALUES ('69', 'Rhone', '69GT|31GT')")
    execute(refonte_database, "INSERT INTO service_departments (service, department) VALUES ('69GT', '69'), ('31GT', '69')")
    return refonte_database


def attach(engine, code):
    execute(engine, f"INSERT INTO email_services (id, service_code) VALUES ('{AGENT}', '{code}')")


def search(client, department="69", label="searchAddress"):
    return client.post("/add-address-search-tracing", json={"DepartmentCode": department, "Libelle": label, "Longitude": 4.83, "Latitude": 45.76}).json()


@pytest.mark.parametrize(("agency", "authorized"), [("69GT", True), ("34GT", False), ("00GT", True)], ids=["own territory", "outside territory", "full access"])
def test_an_address_search_records_whether_the_agent_is_authorized(client, agencies, agency, authorized):
    attach(agencies, agency)

    assert search(client)["IsAuthorized"] is authorized


def test_an_agent_unknown_to_the_directory_is_still_traced(client, agencies):
    tracing = search(client)

    assert (tracing["IsAuthorized"], tracing["UserServiceCode"]) == (False, "")
    assert scalar(agencies, "SELECT count(*) FROM address_search_tracings") == 1


def test_the_covering_agencies_are_returned_aligned(client, agencies):
    attach(agencies, "69GT")

    tracing = search(client)

    assert (tracing["UserServiceName"], tracing["ResearchServiceCode"], tracing["ResearchServiceName"]) == (
        "Agence de Lyon", "69GT|31GT", "Agence de Lyon|Agence de Toulouse",
    )
    assert (tracing["Longitude"], tracing["Latitude"]) == (4.83, 45.76)


def test_the_visit_points_to_the_address_search(client, agencies):
    attach(agencies, "69GT")

    tracing = search(client, label="searchAddress")

    with agencies.connect() as connection:
        visit = connection.execute(text("SELECT * FROM statistique_visites")).mappings().one()
    assert (visit["libelle"], visit["address_search_tracing_id"], visit["service_code"]) == ("searchAddress", tracing["ID"], "69GT")


def test_a_missing_department_is_refused(client):
    response = client.post("/add-address-search-tracing", json={})

    assert (response.status_code, response.json()) == (400, {"errors": "DepartmentCode absent."})


@pytest.mark.parametrize(
    ("agency", "covering", "expected"),
    [
        (Agency("69GT", "Lyon", False), ["69GT", "31GT"], True),
        (Agency("34GT", "Montpellier", False), ["69GT"], False),
        (Agency("00GT", "Direction", True), [], True),
        (None, ["69GT"], False),
        (Agency("69GT", "Lyon", False), [], False),
    ],
    ids=["covering agency", "other agency", "full access", "unknown agent", "department without agency"],
)
def test_the_department_access_policy(agency, covering, expected):
    assert allows(agency, covering) is expected


def upload(client, content, name="photo chantier.png"):
    return client.post("/waitingImage/upload", files={"file": (name, content, "image/png")})


def test_drawing_from_an_empty_table_returns_null(client):
    assert client.get("/waitingImage/random").json() is None


def test_only_active_images_are_drawn(client, refonte_database):
    first = upload(client, PNG).json()
    second = upload(client, PNG).json()
    client.put(f"/waitingImage/{first['ID']}/deactivate")

    assert {client.get("/waitingImage/random").json()["ID"] for _ in range(8)} == {second["ID"]}


def test_an_uploaded_image_is_readable_from_the_file_route(client):
    image = upload(client, PNG).json()

    assert image["Path"].endswith("-photo-chantier.png") and image["Active"] is True
    response = client.get(f"/file/waitingImages/{image['Path']}")
    assert (response.status_code, response.content) == (200, PNG)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment")


@pytest.mark.parametrize(("content", "name"), [(SVG, "logo.svg"), (b"%PDF-1.7 pas une image", "photo.png")], ids=["svg with script", "not an image"])
def test_a_file_that_is_not_an_accepted_image_is_refused(client, refonte_database, content, name):
    response = upload(client, content, name)

    assert (response.status_code, response.json()) == (400, {"errors": "Seules les images sont acceptees."})
    assert scalar(refonte_database, "SELECT count(*) FROM waiting_images") == 0


def test_an_upload_without_file_is_refused(client):
    assert client.post("/waitingImage/upload").json() == {"errors": "Aucun fichier recu."}


def test_the_file_route_refuses_a_path_traversal(client, tmp_path):
    (tmp_path / "secret.txt").write_text("secret")

    assert client.get("/file/waitingImages/..%2Fsecret.txt").status_code == 404
    assert client.get("/file/waitingImages/secret.txt").status_code == 404


def test_activation_switches_the_state_and_an_unknown_image_is_not_created(client, refonte_database):
    image = upload(client, PNG).json()

    assert client.put(f"/waitingImage/{image['ID']}/deactivate").status_code == 204
    assert client.get("/waitingImage/").json() == [{"ID": image["ID"], "Path": image["Path"], "Active": False}]
    assert client.put(f"/waitingImage/{image['ID']}/activate").status_code == 204
    assert client.get("/waitingImage/").json()[0]["Active"] is True

    response = client.put("/waitingImage/999/activate")
    assert (response.status_code, response.json()) == (404, {"error": "Illustration non trouvee"})
    assert scalar(refonte_database, "SELECT count(*) FROM waiting_images") == 1


def test_deleting_removes_the_row_and_the_file(client, refonte_database):
    image = upload(client, PNG).json()

    assert client.delete(f"/waitingImage/{image['ID']}").status_code == 204
    assert scalar(refonte_database, "SELECT count(*) FROM waiting_images") == 0
    assert client.get(f"/file/waitingImages/{image['Path']}").status_code == 404
    assert client.delete(f"/waitingImage/{image['ID']}").status_code == 404
