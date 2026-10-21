import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.auth import current_user
from app.domains.projects import queries
from app.domains.projects.entities import GeolocationFilter, SearchCriteria, classify
from app.main import app

PARIS = (2.3522, 48.8566)


@pytest.fixture
def client(refonte_database):
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def add_project(engine, project_id, position=PARIS, **columns):
    values = {"id": project_id, "is_doc_ged": False, "longitude": position and position[0], "latitude": position and position[1]} | columns
    names = [name for name in values if name not in ("longitude", "latitude")]
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO projects ({', '.join(names)}, geometry) VALUES ({', '.join(':' + name for name in names)}, "
                f"{queries._point_sql('longitude', 'latitude')})"
            ),
            values,
        )


def add_site(engine, site_id, project_id, position=PARIS):
    with engine.begin() as connection:
        connection.execute(
            text(f"INSERT INTO sites (id, project_id, geometry) VALUES (:id, :project_id, {queries._point_sql('longitude', 'latitude')})"),
            {"id": site_id, "project_id": project_id} | queries._position_parameters(None if position is None else _coordinates(position)),
        )


def add_survey(engine, survey_id, site_id, position=PARIS, no_geo_reason_id=None):
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO surveys (id, site_id, no_geo_survey_reason_id, geometry) "
                f"VALUES (:id, :site_id, :reason, {queries._point_sql('longitude', 'latitude')})"
            ),
            {"id": survey_id, "site_id": site_id, "reason": no_geo_reason_id}
            | queries._position_parameters(None if position is None else _coordinates(position)),
        )


def _coordinates(position):
    from app.domains.projects.entities import Coordinates

    return Coordinates(*position)


def encoded(identifier):
    return base64.b64encode(identifier.encode()).decode()


def ids(client, query=""):
    response = client.get(f"/projects{query}")
    assert response.status_code == 200
    return [item["ID"] for item in response.json()["items"]]


def scalar(engine, sql, **parameters):
    with engine.connect() as connection:
        return connection.execute(text(sql), parameters).scalar()


@pytest.fixture
def bastille(refonte_database):
    add_project(refonte_database, "A-2026-001", name="Chantier Bastille", city="PARIS", city_agency="IDF", code_metier="G2", client="VINCI", is_doc_ged=True)
    add_site(refonte_database, "S-1", "A-2026-001")
    add_survey(refonte_database, "SV-1", "S-1")
    add_survey(refonte_database, "SV-2", "S-1", position=None)
    add_survey(refonte_database, "SV-3_PM6'", "S-1")
    return refonte_database


def test_the_project_list_keeps_the_items_count_envelope_and_legacy_fields(client, bastille):
    body = client.get("/projects").json()
    project = body["items"][0]

    assert body["count"] == 1
    assert (project["ID"], project["NbSurveys"], project["NbSurveysGeoloc"]) == ("A-2026-001", 3, 2)
    assert project["Latitude"] == pytest.approx(48.8566)
    assert project["IsDocGed"] is True
    assert project["GeolocationStatus"] == "surveys_to_geolocate"
    assert set(project) == {
        "ID", "Name", "City", "Latitude", "Longitude", "Altitude", "NoGeoProjectReasonID", "ProjectTypeID", "CityAgency",
        "CodeMetier", "Client", "UUID", "ExterneId", "UrlID", "IsDocGed", "IsDocGedUpdatedBy", "IsDocGedUpdatedAt", "UserEmail",
        "SystemeGeo", "LatitudeSaisie",
        "LongitudeSaisie", "NbSurveys", "NbSurveysGeoloc", "GeolocationStatus", "UpdatedAt",
    }


def test_the_project_sheet_has_no_guessed_status(client, bastille):
    project = client.get("/projects/A-2026-001").json()

    assert (project["Name"], project["GeolocationStatus"], project["NbSurveys"]) == ("Chantier Bastille", None, 0)


def test_the_project_sheet_counts_its_sites_and_the_list_does_not(client, bastille):
    add_project(bastille, "SANS-CHANTIER")

    assert client.get("/projects/A-2026-001").json()["SiteCount"] == 1
    assert client.get("/projects/SANS-CHANTIER").json()["SiteCount"] == 0
    assert all("SiteCount" not in item for item in client.get("/projects").json()["items"])


def test_an_unknown_project_answers_not_found(client, bastille):
    response = client.get("/projects/INCONNUE")

    assert (response.status_code, response.json()) == (404, {"errors": "Affaire introuvable : INCONNUE"})


def test_the_surveys_are_a_plain_list_with_the_original_entry(client, bastille):
    surveys = client.get("/projects/A-2026-001/surveys").json()

    assert [survey["ID"] for survey in surveys] == ["SV-1", "SV-2", "SV-3_PM6'"]
    assert {"SystemeGeo", "LatitudeSaisie", "LongitudeSaisie"} <= set(surveys[0])
    assert (surveys[1]["Latitude"], surveys[0]["Pressures"], surveys[0]["Lithologies"]) == (0.0, [], [])


def test_the_reference_lists_are_exposed(client, bastille):
    with bastille.begin() as connection:
        connection.execute(text("INSERT INTO project_types (id, libelle) VALUES (2, 'Étude'), (1, 'Mission')"))

    assert client.get("/city-agencies").json() == ["IDF"]
    assert client.get("/codes-metier").json() == ["G2"]
    assert client.get("/project-types").json() == [{"ID": 1, "Libelle": "Mission"}, {"ID": 2, "Libelle": "Étude"}]
    assert client.get("/no-geo-project-reasons").json() == []
    assert client.get("/no-geo-survey-reasons").json() == []


@pytest.mark.parametrize(
    ("query", "count"),
    [
        ("?selectedGeo=3", 1),
        ("?selectedGeo=1", 0),
        ("?selectedGeo=4", 0),
        ("?selectedSurvey=1", 1),
        ("?selectedSurvey=2", 0),
        ("?selectedGeds=1", 1),
        ("?selectedGeds=2", 0),
        ("?projectId=A-2026&name=bastille&city=par&client=vin&cityAgency=IDF&codeMetier=G2", 1),
        ("?name=autre", 0),
    ],
)
def test_the_filters_are_applied(client, bastille, query, count):
    assert client.get(f"/projects{query}").json()["count"] == count


@pytest.mark.parametrize("query", ["A-2026", "a-2026-0", "A2026", "a.2026.", " A 2026 001"])
def test_the_project_number_filter_ignores_case_and_punctuation(client, bastille, query):
    assert ids(client, f"?projectId={query}") == ["A-2026-001"]


def test_the_project_number_filter_stays_a_prefix(client, bastille):
    assert ids(client, "?projectId=2026") == []


def test_the_real_front_request_with_undefined_filters_is_accepted(client, bastille):
    body = client.get(
        "/projects?projectId=&name=&city=&cityAgency=&codeMetier=&client="
        "&selectedGeo=undefined&selectedSurvey=undefined&selectedGeds=undefined&limit=100&offset=-100&withoutPaginate=0"
    ).json()

    assert body["count"] == 1


def test_without_paginate_the_total_is_not_computed(client, bastille):
    body = client.get("/projects?withoutPaginate=1").json()

    assert (len(body["items"]), body["count"]) == (1, 0)


@pytest.fixture
def sortable(refonte_database):
    for project_id, name, city, client_name in [
        ("IP.01", "Zénith", "TOULOUSE", "VINCI"),
        ("IP.02", "École", "ALBI", "BOUYGUES"),
        ("IP.03", "abri", "TOULOUSE", "EIFFAGE"),
        ("IP.04", "Église", "CASTRES", None),
    ]:
        add_project(refonte_database, project_id, name=name, city=city, client=client_name)
    add_site(refonte_database, "S-1", "IP.04")
    add_survey(refonte_database, "SV-1", "S-1")
    add_site(refonte_database, "S-2", "IP.02")
    add_survey(refonte_database, "SV-2", "S-2")
    return refonte_database


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("", ["IP.01", "IP.02", "IP.03", "IP.04"]),
        ("?sort=number&order=desc", ["IP.04", "IP.03", "IP.02", "IP.01"]),
        ("?sort=name&order=asc", ["IP.03", "IP.02", "IP.04", "IP.01"]),
        ("?sort=name&order=desc", ["IP.01", "IP.04", "IP.02", "IP.03"]),
        ("?sort=city&order=desc", ["IP.01", "IP.03", "IP.04", "IP.02"]),
        ("?sort=name&order=asc&offset=2&limit=1", ["IP.04"]),
        ("?selectedSurvey=1&sort=name&order=desc", ["IP.04", "IP.02"]),
    ],
    ids=[
        "by number by default",
        "number descending",
        "french alphabetical order ignoring accents and case",
        "french alphabetical order descending",
        "ties broken by ascending number",
        "sort before pagination",
        "sort with a survey filter",
    ],
)
def test_the_projects_are_sorted(client, sortable, query, expected):
    assert ids(client, query) == expected


def test_a_missing_value_is_sorted_last_both_ways(client, sortable):
    assert ids(client, "?sort=client&order=asc")[3] == "IP.04"
    assert ids(client, "?sort=client&order=desc")[3] == "IP.04"


def test_an_unknown_sort_is_refused(client, sortable):
    assert client.get("/projects?sort=p.id").status_code == 400


@pytest.fixture
def geolocation_cases(refonte_database):
    add_project(refonte_database, "P-GEO-SANS-SONDAGE")
    add_project(refonte_database, "P-GEO-COMPLETE")
    add_site(refonte_database, "S-COMPLETE", "P-GEO-COMPLETE")
    add_survey(refonte_database, "SV-1", "S-COMPLETE")
    add_survey(refonte_database, "SV-2", "S-COMPLETE", position=None, no_geo_reason_id=3)
    add_project(refonte_database, "P-GEO-PARTIELLE")
    add_site(refonte_database, "S-PARTIELLE", "P-GEO-PARTIELLE")
    add_survey(refonte_database, "SV-3", "S-PARTIELLE")
    add_survey(refonte_database, "SV-4", "S-PARTIELLE", position=None)
    add_project(refonte_database, "P-SANS-POSITION", position=None)
    add_project(refonte_database, "P-TYPE1-COMPLET", position=None, project_type_id=1)
    add_site(refonte_database, "S-TYPE1", "P-TYPE1-COMPLET", position=None)
    add_survey(refonte_database, "SV-5", "S-TYPE1")
    add_project(refonte_database, "P-TYPE2-PARTIEL", position=None, project_type_id=2)
    add_site(refonte_database, "S-TYPE2", "P-TYPE2-PARTIEL", position=None)
    add_survey(refonte_database, "SV-6", "S-TYPE2")
    add_survey(refonte_database, "SV-7", "S-TYPE2", position=None)
    add_project(refonte_database, "P-TYPE1-SANS-SONDAGE", position=None, project_type_id=1)
    add_project(refonte_database, "P-MOTIF-NON-GEO", position=None, no_geo_project_reason_id=7)
    return refonte_database


@pytest.mark.parametrize("geolocation_filter", list(GeolocationFilter))
def test_the_sql_filter_and_the_business_rule_select_the_same_projects(geolocation_cases, geolocation_filter):
    with geolocation_cases.connect() as connection:
        via_sql, _ = queries.search(connection, SearchCriteria(geolocation_filter=geolocation_filter, limit=1000))
        everything, _ = queries.search(connection, SearchCriteria(limit=1000))

    via_rule = [project.id for project, tally in everything if geolocation_filter.matches(classify(project, tally))]
    assert sorted(project.id for project, _ in via_sql) == sorted(via_rule)
    assert via_rule


def test_filter_four_gathers_the_excluded_and_the_unclassified(client, geolocation_cases):
    assert sorted(ids(client, "?selectedGeo=4")) == ["P-MOTIF-NON-GEO", "P-TYPE1-SANS-SONDAGE"]


def test_the_position_makes_a_faithful_round_trip_through_postgis(client, geolocation_cases):
    project = client.get("/projects/P-GEO-COMPLETE").json()

    assert (project["Longitude"], project["Latitude"]) == pytest.approx(PARIS, abs=1e-7)


@pytest.fixture
def status_cases(refonte_database):
    add_project(refonte_database, "IP.02.0222")
    add_site(refonte_database, "S-1", "IP.02.0222")
    add_survey(refonte_database, "SV-1", "S-1")
    add_project(refonte_database, "IP.02.0227")
    add_site(refonte_database, "S-2", "IP.02.0227")
    add_survey(refonte_database, "SV-2", "S-2")
    add_survey(refonte_database, "SV-3", "S-2", position=None)
    add_project(refonte_database, "IP.04.0176", position=None)
    return refonte_database


def test_the_status_of_each_requested_project_is_returned_in_one_call(client, status_cases):
    response = client.post("/projects/geolocation-statuses", json={"ids": ["IP.02.0222", "IP.02.0227", "IP.04.0176", "INCONNUE"]})

    assert response.json() == {
        "statuses": {"IP.02.0222": "geolocated", "IP.02.0227": "surveys_to_geolocate", "IP.04.0176": "to_geolocate"}
    }


def test_the_status_is_the_one_of_the_project_list(client, status_cases):
    via_statuses = client.post("/projects/geolocation-statuses", json={"ids": ["IP.02.0227"]}).json()["statuses"]["IP.02.0227"]

    assert client.get("/projects?projectId=IP.02.0227").json()["items"][0]["GeolocationStatus"] == via_statuses


@pytest.mark.parametrize(
    "payload",
    [{}, {"ids": {"a": "IP.02.0222"}}, {"ids": [42]}, {"ids": ["  "]}, {"ids": ["X" * 65]}, {"ids": [f"P{i}" for i in range(1001)]}],
    ids=["no list", "list as object", "non-text number", "empty number", "oversized number", "more than a thousand"],
)
def test_a_malformed_status_request_is_refused(client, status_cases, payload):
    assert client.post("/projects/geolocation-statuses", json=payload).status_code == 400


def test_relocating_a_project_saves_altitude_and_moves_its_sites(client, bastille):
    response = client.put(f"/projects/{encoded('A-2026-001')}", json={"ID": "A-2026-001", "Latitude": 45.7640, "Longitude": 4.8357, "Altitude": 172.5})

    assert response.status_code == 200
    assert response.json()["Latitude"] == pytest.approx(45.7640)
    assert response.json()["UpdatedAt"].endswith("+00:00")
    assert scalar(bastille, "SELECT altitude FROM projects WHERE id = 'A-2026-001'") == pytest.approx(172.5)
    assert scalar(bastille, "SELECT ST_Y(geometry) FROM sites WHERE id = 'S-1'") == pytest.approx(45.7640)
    assert scalar(bastille, "SELECT fiability FROM sites WHERE id = 'S-1'") == 1


def test_a_reason_marks_a_project_not_geolocatable_without_moving_it(client, bastille):
    response = client.put(f"/projects/{encoded('A-2026-001')}", json={"NoGeoProjectReasonID": 3})

    assert response.json()["NoGeoProjectReasonID"] == 3
    assert response.json()["Latitude"] == pytest.approx(48.8566)


def test_a_new_position_clears_the_reason(client, bastille):
    client.put(f"/projects/{encoded('A-2026-001')}", json={"NoGeoProjectReasonID": 3})
    response = client.put(f"/projects/{encoded('A-2026-001')}", json={"Latitude": 45.7, "Longitude": 4.8, "NoGeoProjectReasonID": 3})

    assert response.json()["NoGeoProjectReasonID"] is None


def test_an_invalid_base64_identifier_is_refused(client, bastille):
    assert client.put("/projects/@@@pas-du-base64@@@", json={}).status_code == 400


def test_a_survey_with_an_apostrophe_is_relocated_with_its_altitude(client, bastille):
    response = client.put(f"/surveys/{encoded(chr(83) + 'V-3_PM6' + chr(39))}", json={"Longitude": 4.8357, "Latitude": 45.7640, "Altitude": 172.5})

    assert response.status_code == 200
    assert scalar(bastille, "SELECT ST_Y(geometry) FROM surveys WHERE id = :id", id="SV-3_PM6'") == pytest.approx(45.7640)
    assert scalar(bastille, "SELECT altitude FROM surveys WHERE id = :id", id="SV-3_PM6'") == pytest.approx(172.5)


def test_relocating_a_survey_clears_its_reason(client, bastille):
    client.put(f"/surveys/{encoded('SV-2')}", json={"NoGeoSurveyReasonID": 2})
    assert scalar(bastille, "SELECT no_geo_survey_reason_id FROM surveys WHERE id = 'SV-2'") == 2

    client.put(f"/surveys/{encoded('SV-2')}", json={"Longitude": 4.8, "Latitude": 45.7})
    assert scalar(bastille, "SELECT no_geo_survey_reason_id FROM surveys WHERE id = 'SV-2'") is None


@pytest.mark.parametrize(
    ("path", "body", "status"),
    [
        (f"/surveys/{encoded('SV-1')}", {"Longitude": 4.8, "Latitude": 45.7, "Altitude": "haut"}, 400),
        (f"/surveys/{encoded('INCONNU')}", {"Longitude": 4.8, "Latitude": 45.7}, 404),
        (f"/projects/{encoded('INCONNUE')}", {"Longitude": 4.8, "Latitude": 45.7}, 404),
        (f"/surveys/{encoded('SV-1')}", {"Longitude": 400, "Latitude": 45.7}, 400),
    ],
    ids=["non-numeric altitude", "unknown survey", "unknown project", "out-of-bounds position"],
)
def test_an_invalid_relocation_is_refused(client, bastille, path, body, status):
    assert client.put(path, json=body).status_code == status


@pytest.mark.parametrize("path", [f"/projects/{encoded('A-1')}", f"/surveys/{encoded('SV-1')}"])
def test_a_malformed_json_body_is_refused(client, bastille, path):
    assert client.put(path, content="{pas du json", headers={"Content-Type": "application/json"}).status_code == 400


def test_the_ged_presence_is_declared_by_hand_and_traced(client, bastille):
    response = client.patch("/projects/A-2026-001/ged-presence", json={"IsDocGed": False})

    assert response.status_code == 200
    assert response.json()["IsDocGed"] is False
    assert response.json()["IsDocGedUpdatedBy"] == "test@fondasol.fr"
    assert response.json()["IsDocGedUpdatedAt"].endswith("+00:00")
    assert scalar(bastille, "SELECT is_doc_ged FROM projects WHERE id = 'A-2026-001'") is False
    assert scalar(bastille, "SELECT is_doc_ged_updated_by FROM projects WHERE id = 'A-2026-001'") == "test@fondasol.fr"
    assert scalar(bastille, "SELECT updated_at FROM projects WHERE id = 'A-2026-001'") is None
    assert ids(client, "?selectedGeds=2") == ["A-2026-001"]


def test_a_ged_presence_never_declared_has_no_trace(client, bastille):
    body = client.get("/projects/A-2026-001").json()

    assert body["IsDocGedUpdatedBy"] == ""
    assert body["IsDocGedUpdatedAt"] is None


@pytest.mark.parametrize("body", [{}, {"IsDocGed": "oui"}, {"IsDocGed": 1}, {"IsDocGed": None}])
def test_an_invalid_ged_presence_is_refused(client, bastille, body):
    assert client.patch("/projects/A-2026-001/ged-presence", json=body).status_code == 400


def test_the_ged_presence_of_an_unknown_project_is_not_found(client, bastille):
    assert client.patch("/projects/INCONNUE/ged-presence", json={"IsDocGed": True}).status_code == 404


def test_a_survey_added_to_a_project_is_created_on_its_site(client, bastille):
    response = client.post("/projects/A-2026-001/surveys", json={"Name": "NvS1", "Latitude": 48.8570, "Longitude": 2.3530, "Altitude": 35.5})

    assert response.status_code == 201
    assert response.json()["ID"] == "A-2026-001_NvS1"
    assert scalar(bastille, "SELECT site_id FROM surveys WHERE id = 'A-2026-001_NvS1'") == "S-1"
    assert scalar(bastille, "SELECT altitude FROM surveys WHERE id = 'A-2026-001_NvS1'") == pytest.approx(35.5)
    assert scalar(bastille, "SELECT ST_Y(geometry) FROM surveys WHERE id = 'A-2026-001_NvS1'") == pytest.approx(48.8570)


def test_a_survey_already_present_is_not_created_twice(client, bastille):
    body = {"Name": "1", "Latitude": 48.8570, "Longitude": 2.3530}

    assert client.post("/projects/A-2026-001/surveys", json=body).status_code == 201
    assert client.post("/projects/A-2026-001/surveys", json=body).status_code == 409


@pytest.mark.parametrize(
    "body",
    [{"Name": "SC/1", "Latitude": 48.8, "Longitude": 2.3}, {"Name": "SC9", "Latitude": 48.8}, {"Latitude": 48.8, "Longitude": 2.3}],
    ids=["invalid name", "no longitude", "no name"],
)
def test_a_survey_with_an_invalid_name_or_without_position_is_refused(client, bastille, body):
    assert client.post("/projects/A-2026-001/surveys", json=body).status_code == 400


def test_a_survey_cannot_be_added_to_an_unknown_project_or_one_without_site(client, bastille):
    add_project(bastille, "SANS-CHANTIER")
    body = {"Name": "S1", "Latitude": 48.8, "Longitude": 2.3}

    assert client.post("/projects/INCONNUE/surveys", json=body).status_code == 404
    assert client.post("/projects/SANS-CHANTIER/surveys", json=body).status_code == 422


def test_a_project_number_with_a_slash_is_reachable(client, refonte_database):
    add_project(refonte_database, "PR.GT01.25.0082 / DE-16511")
    add_site(refonte_database, "S-1", "PR.GT01.25.0082 / DE-16511")
    path = "/projects/PR.GT01.25.0082%20%2F%20DE-16511"

    assert client.get(path).json()["ID"] == "PR.GT01.25.0082 / DE-16511"
    assert client.get(f"{path}/surveys").json() == []
    assert client.post(f"{path}/surveys", json={"Name": "S1", "Latitude": 48.8, "Longitude": 2.3}).json()["ID"] == "PR.GT01.25.0082 / DE-16511_S1"
    assert client.put(f"/projects/{encoded('PR.GT01.25.0082 / DE-16511')}", json={"Altitude": 12}).json()["Altitude"] == 12
    assert client.patch(f"{path}/ged-presence", json={"IsDocGed": True}).json()["IsDocGed"] is True


def test_a_base64_identifier_holding_a_slash_is_decoded(client, refonte_database):
    add_project(refonte_database, "P??")

    assert encoded("P??") == "UD8/"
    assert client.put(f"/projects/{encoded('P??')}", json={"Altitude": 3}).status_code == 200


def test_a_request_without_token_is_refused(client, bastille):
    app.dependency_overrides.clear()

    assert client.get("/projects").status_code == 401
