import pytest
from sqlalchemy import text

from tests.domains.projects.test_routes import add_project, add_survey
from tests.domains.survey_data.test_routes import AGENT, client  # noqa: F401

PROJECT = "31GT.23.0165"
SURVEY = "31GT.23.0165_SP1"

FULL = {
    "groundElevation": 144.45,
    "lithology": [{"depthStart": 0, "depthEnd": 1.2, "description": "Remblais"}, {"depthStart": 1.2, "depthEnd": 3.5, "description": "Sable argileux marron"}],
    "pressures": [{"depth": 1.5, "em": None, "pl": 0.62, "pf": 0.45, "p0": 0.02, "plp0": 0.6, "pfp0": 0.43}],
    "penetrometer": {
        "machineTypeId": None,
        "hammerDropHeight": 0.75,
        "hammerMass": 63.5,
        "anvilMass": 10,
        "rodMass": 30,
        "tipSection": 20,
        "readings": [{"depth": 0.1, "blowCount": 5, "qd": 7.17}, {"depth": 0.2, "blowCount": 6, "qd": 8.6}],
    },
    "waterLevels": {"referentiel": "NGF", "measures": [{"date": "2026-01-15", "depth": 3.2, "ref": 141.25}, {"date": "2026-02-15", "depth": 9999, "ref": None}]},
    "referenceLevels": {"standardId": 1, "referentiel": "NGF", "levels": {"eb": {"depth": 1, "ref": None}, "eh": {"depth": 5, "ref": None}, "ee": {"depth": 10, "ref": None}}},
    "hydrodynamics": {
        "tests": [{"mode": "withdrawal", "longDurationPumping": True, "top": 2, "base": 5, "permeability": 1.5e-5, "transmissivity": None, "storage": None, "facies": "Sables limoneux", "notes": None}],
    },
}


@pytest.fixture
def survey(refonte_database):
    add_project(refonte_database, PROJECT)
    add_survey(refonte_database, SURVEY, PROJECT)
    with refonte_database.begin() as connection:
        connection.execute(text("INSERT INTO referentiels (code, label_fr) VALUES ('NGF', 'NGF')"))
        connection.execute(text("INSERT INTO standards (id, code) VALUES (1, 'DTU 14.1')"))
    return refonte_database


def scalar(engine, sql, **parameters):
    with engine.begin() as connection:
        return connection.execute(text(sql), parameters).scalar()


def test_an_untouched_survey_reads_empty(client, survey):  # noqa: F811
    assert client.get(f"/survey-data/{SURVEY}").json() == {
        "surveyId": SURVEY,
        "groundElevation": None,
        "lithology": [],
        "pressures": [],
        "penetrometer": None,
        "waterLevels": {"referentiel": None, "measures": []},
        "referenceLevels": {"standardId": None, "referentiel": None, "levels": {level: {"depth": None, "ref": None} for level in ("eb", "eh", "ee")}},
        "hydrodynamics": {"tests": []},
    }


def test_saves_every_section_and_reads_it_back(client, survey):  # noqa: F811
    response = client.put(f"/survey-data/{SURVEY}", json=FULL)

    assert response.status_code == 200
    saved = response.json()
    assert saved == client.get(f"/survey-data/{SURVEY}").json()
    assert {key: saved[key] for key in FULL} == FULL
    flags = "SELECT row(has_lithology, has_pressuremeter, has_penetrometer, has_water_levels, is_water_testing, depth_max, altitude)::text FROM surveys WHERE id = :id"
    assert scalar(survey, flags, id=SURVEY) == "(t,t,t,t,t,3.5,144.45)"
    assert scalar(survey, "SELECT site_id FROM gw_reference_levels WHERE survey_id = :id", id=SURVEY) == PROJECT
    assert scalar(survey, "SELECT long_duration_pumping FROM water_testing_parameters WHERE survey_id = :id", id=SURVEY) is True
    assert scalar(survey, "SELECT count(*) FROM geolocation_correction_history WHERE survey_id = :id", id=SURVEY) == 1


def test_saving_again_replaces_each_section(client, survey):  # noqa: F811
    client.put(f"/survey-data/{SURVEY}", json=FULL)

    response = client.put(f"/survey-data/{SURVEY}", json={"groundElevation": 144.45, "lithology": [{"depthStart": 0, "depthEnd": 2, "description": "Craie"}]})

    assert response.status_code == 200
    assert response.json()["lithology"] == [{"depthStart": 0, "depthEnd": 2, "description": "Craie"}]
    for table in ("pressures", "penetrometer_tests", "water_levels_manual", "gw_reference_levels", "water_testing_parameters"):
        assert scalar(survey, f"SELECT count(*) FROM {table} WHERE survey_id = :id", id=SURVEY) == 0, table
    assert scalar(survey, "SELECT count(*) FROM penetrometer_readings") == 0
    assert scalar(survey, "SELECT has_pressuremeter OR has_penetrometer OR is_water_testing FROM surveys WHERE id = :id", id=SURVEY) is False
    assert scalar(survey, "SELECT count(*) FROM geolocation_correction_history WHERE survey_id = :id", id=SURVEY) == 1


def test_keeps_the_site_reference_levels(client, survey):  # noqa: F811
    with survey.begin() as connection:
        connection.execute(text("INSERT INTO gw_reference_levels (site_id, structure, eb_depth) VALUES (:site, 'Bât. A', 4)"), {"site": PROJECT})

    client.put(f"/survey-data/{SURVEY}", json={})

    assert scalar(survey, "SELECT count(*) FROM gw_reference_levels WHERE site_id = :site AND survey_id IS NULL", site=PROJECT) == 1


def test_refuses_business_rule_violations_without_writing_anything(client, survey):  # noqa: F811
    client.put(f"/survey-data/{SURVEY}", json=FULL)

    response = client.put(f"/survey-data/{SURVEY}", json=FULL | {"lithology": [{"depthStart": 0, "depthEnd": 1, "description": ""}], "groundElevation": 10})

    assert response.status_code == 422
    assert response.json() == {"errors": "Lithologie, couche 1 : description obligatoire."}
    assert scalar(survey, "SELECT count(*) FROM lithologies WHERE survey_id = :id", id=SURVEY) == 2
    assert scalar(survey, "SELECT altitude FROM surveys WHERE id = :id", id=SURVEY) == 144.45


def test_unknown_survey_and_malformed_body(client, survey):  # noqa: F811
    assert client.get("/survey-data/inconnu").status_code == 404
    assert client.put("/survey-data/inconnu", json={}).status_code == 404
    assert client.put(f"/survey-data/{SURVEY}", json={"lithology": "Remblais"}).status_code == 400


def test_survey_ids_with_a_slash_or_an_apostrophe(client, refonte_database):  # noqa: F811
    add_project(refonte_database, PROJECT)
    add_survey(refonte_database, "SV-3/PM6'", PROJECT)
    assert client.get("/survey-data/SV-3%2FPM6%27").json()["surveyId"] == "SV-3/PM6'"
