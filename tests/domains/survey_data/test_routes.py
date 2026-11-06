import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.auth import current_user
from app.core.profile import Profile, current_profile
from app.main import app
from tests.domains.projects.test_routes import add_project, add_survey

AGENT = Profile(id="0d4f5c2e-7a3b-4c1d-9e8f-123456789abc", azure_oid="oid-agent", email="agent@fondasol.fr", display_name="Agent Test")
SITE = "95GT.23.0154"
LEVELS = {"eb": {"depth": 3.5, "ref": 31.5}, "eh": {"depth": 4, "ref": None}, "ee": {"depth": None, "ref": None}}


@pytest.fixture
def client(refonte_database):
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"
    app.dependency_overrides[current_profile] = lambda: AGENT
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def site(refonte_database):
    add_project(refonte_database, SITE, altitude=35.0)
    with refonte_database.begin() as connection:
        connection.execute(text("INSERT INTO referentiels (code, label_fr, label_en, position) VALUES ('NGF', 'Nivellement', 'Levelling', 1), ('LUREF', 'Luref', NULL, 2)"))
        connection.execute(text("INSERT INTO standards (id, code, label, position) VALUES (1, 'DTU 14.1', 'Cuvelage', 1), (2, 'Eurocode 7', NULL, 2)"))
    return refonte_database


def rows(engine):
    with engine.begin() as connection:
        return [dict(row) for row in connection.execute(text("SELECT site_id, survey_id, structure, standard_id, referentiel, eb_depth, eb_ref, eh_depth FROM gw_reference_levels ORDER BY structure")).mappings()]


def test_lists_referentiels_standards_and_machine_types_in_order(client, site):
    with site.begin() as connection:
        connection.execute(text("INSERT INTO penetrometer_machine_types (type, hammer_mass, hammer_drop_height, rod_mass, anvil_mass) VALUES ('PDB 64 kg', 64, 0.75, 6.3, 10)"))

    assert client.get("/referentiels").json() == [{"code": "NGF", "labelFr": "Nivellement", "labelEn": "Levelling"}, {"code": "LUREF", "labelFr": "Luref", "labelEn": None}]
    assert client.get("/standards").json() == [{"id": 1, "code": "DTU 14.1", "label": "Cuvelage"}, {"id": 2, "code": "Eurocode 7", "label": None}]
    [machine] = client.get("/penetrometer-machine-types").json()
    assert machine == {"id": machine["id"], "type": "PDB 64 kg", "hammerMass": 64, "hammerDropHeight": 0.75, "rodMass": 6.3, "anvilMass": 10}


def test_a_site_without_structures_returns_its_altitude(client, site):
    assert client.get(f"/sites/{SITE}/reference-levels").json() == {"siteId": SITE, "groundElevation": 35.0, "structures": []}


def test_replaces_the_site_structures_and_returns_them(client, site):
    first = client.put(
        f"/sites/{SITE}/reference-levels",
        json={"structures": [{"structure": "Bât. B", "standardId": 1, "referentiel": "NGF", "levels": LEVELS}, {"structure": "Bât. A", "standardId": None, "referentiel": None}]},
    )
    assert first.status_code == 200
    assert [entry["structure"] for entry in first.json()["structures"]] == ["Bât. A", "Bât. B"]
    assert first.json()["structures"][1]["levels"]["eb"] == {"depth": 3.5, "ref": 31.5}

    second = client.put(f"/sites/{SITE}/reference-levels", json={"structures": [{"structure": "Immeuble", "standardId": 2, "referentiel": "LUREF", "levels": {"ee": {"depth": 1}}}]})
    assert second.status_code == 200
    assert rows(site) == [
        {"site_id": SITE, "survey_id": None, "structure": "Immeuble", "standard_id": 2, "referentiel": "LUREF", "eb_depth": None, "eb_ref": None, "eh_depth": None}
    ]
    assert client.get(f"/sites/{SITE}/reference-levels").json()["structures"][0]["structure"] == "Immeuble"


def test_keeps_the_levels_entered_for_a_survey_of_the_site(client, site):
    add_survey(site, "SP1", SITE)
    with site.begin() as connection:
        connection.execute(text("INSERT INTO gw_reference_levels (survey_id, site_id, eb_depth) VALUES ('SP1', :site, 2)"), {"site": SITE})

    assert client.put(f"/sites/{SITE}/reference-levels", json={"structures": []}).status_code == 200
    assert [(row["survey_id"], row["eb_depth"]) for row in rows(site)] == [("SP1", 2.0)]
    assert client.get(f"/sites/{SITE}/reference-levels").json()["structures"] == []


def test_refuses_a_level_order_against_the_rule_without_saving_anything(client, site):
    client.put(f"/sites/{SITE}/reference-levels", json={"structures": [{"structure": "Bât. A", "standardId": 1, "referentiel": "NGF", "levels": LEVELS}]})

    response = client.put(
        f"/sites/{SITE}/reference-levels",
        json={"structures": [{"structure": "Bât. A", "standardId": 1, "referentiel": "NGF", "levels": {"eh": {"depth": 10}, "ee": {"depth": 5}}}]},
    )

    assert response.status_code == 422
    assert response.json() == {"errors": "Bât. A : EE doit être supérieur ou égal à EH (m/TA)."}
    assert [row["eb_depth"] for row in rows(site)] == [3.5]


@pytest.mark.parametrize(
    ("structures", "message"),
    [
        ([{"structure": "A"}, {"structure": "a"}], "ouvrage en double"),
        ([{"structure": "A", "levels": {"eb": {"depth": 1}}}], "norme obligatoire"),
        ([{"structure": "A", "standardId": 9, "referentiel": "NGF"}], "norme inconnue (9)"),
        ([{"structure": "A", "standardId": 1, "referentiel": "IGN69"}], "référentiel inconnu (IGN69)"),
    ],
)
def test_refuses_business_rule_violations(client, site, structures, message):
    response = client.put(f"/sites/{SITE}/reference-levels", json={"structures": structures})
    assert response.status_code == 422
    assert message in response.json()["errors"]


def test_refuses_a_malformed_body(client, site):
    assert client.put(f"/sites/{SITE}/reference-levels", json={"structures": "Bât. A"}).status_code == 400


def test_unknown_site_is_404(client, site):
    assert client.get("/sites/inconnu/reference-levels").status_code == 404
    assert client.put("/sites/inconnu/reference-levels", json={"structures": []}).status_code == 404


def test_site_ids_with_a_slash_are_accepted(client, refonte_database):
    add_project(refonte_database, "PR.GT01.25.0082 / DE-16511")
    assert client.get("/sites/PR.GT01.25.0082%20%2F%20DE-16511/reference-levels").json()["siteId"] == "PR.GT01.25.0082 / DE-16511"


def test_routes_require_a_token(refonte_database):
    with TestClient(app) as anonymous:
        assert anonymous.get("/referentiels").status_code == 401
        assert anonymous.get(f"/sites/{SITE}/reference-levels").status_code == 401


def history(engine):
    with engine.begin() as connection:
        return [dict(row) for row in connection.execute(text("SELECT site_id, altitude, user_email FROM geolocation_correction_history ORDER BY horodatage")).mappings()]


def altitude(engine):
    with engine.begin() as connection:
        return connection.execute(text("SELECT altitude FROM sites WHERE id = :site"), {"site": SITE}).scalar()


def test_a_new_ground_elevation_becomes_the_site_altitude_traced_in_the_history(client, site):
    response = client.put(f"/sites/{SITE}/reference-levels", json={"structures": [], "groundElevation": 144.45})

    assert response.status_code == 200
    assert response.json()["groundElevation"] == 144.45
    assert altitude(site) == 144.45
    assert history(site) == [{"site_id": SITE, "altitude": 35.0, "user_email": AGENT.email}]


def test_an_unchanged_or_absent_ground_elevation_leaves_the_site_and_the_history_alone(client, site):
    client.put(f"/sites/{SITE}/reference-levels", json={"structures": [], "groundElevation": 35.0})
    client.put(f"/sites/{SITE}/reference-levels", json={"structures": []})

    assert altitude(site) == 35.0
    assert history(site) == []


def test_a_null_ground_elevation_clears_the_site_altitude(client, site):
    client.put(f"/sites/{SITE}/reference-levels", json={"structures": [], "groundElevation": None})

    assert altitude(site) is None
    assert [row["altitude"] for row in history(site)] == [35.0]


@pytest.mark.parametrize("ground_elevation", ["144", 1e6, True])
def test_refuses_an_invalid_ground_elevation(client, site, ground_elevation):
    assert client.put(f"/sites/{SITE}/reference-levels", json={"structures": [], "groundElevation": ground_elevation}).status_code == 400
    assert altitude(site) == 35.0


def test_a_rejected_save_does_not_change_the_altitude(client, site):
    response = client.put(
        f"/sites/{SITE}/reference-levels",
        json={"structures": [{"structure": "", "standardId": None, "referentiel": None}], "groundElevation": 144.45},
    )

    assert response.status_code == 422
    assert altitude(site) == 35.0
    assert history(site) == []
