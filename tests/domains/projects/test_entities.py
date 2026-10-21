import pytest

from app.core.errors import InvalidRequest
from app.domains.projects.entities import (
    Coordinates,
    GedFilter,
    GeolocationFilter,
    GeolocationStatus,
    Project,
    SearchCriteria,
    Site,
    SurveyPresenceFilter,
    SurveyTally,
    classify,
    coordinates_from_geolocation,
    nearest_site,
    php_float,
    php_int,
    search_criteria,
    survey_name,
)

PARIS = Coordinates(2.3522, 48.8566)


def project(coordinates=PARIS, no_geo_reason_id=None, type_id=None):
    return Project("A-1", coordinates=coordinates, no_geo_reason_id=no_geo_reason_id, type_id=type_id)


@pytest.mark.parametrize(
    ("subject", "tally", "status"),
    [
        (project(no_geo_reason_id=4), SurveyTally(), GeolocationStatus.EXCLUDED),
        (project(no_geo_reason_id=0), SurveyTally(), GeolocationStatus.GEOLOCATED),
        (project(), SurveyTally(), GeolocationStatus.GEOLOCATED),
        (project(), SurveyTally(12, 12), GeolocationStatus.GEOLOCATED),
        (project(), SurveyTally(12, 9), GeolocationStatus.SURVEYS_TO_GEOLOCATE),
        (project(coordinates=None), SurveyTally(), GeolocationStatus.TO_GEOLOCATE),
        (project(coordinates=None, type_id=1), SurveyTally(5, 5), GeolocationStatus.GEOLOCATED),
        (project(coordinates=None, type_id=2), SurveyTally(5, 2), GeolocationStatus.SURVEYS_TO_GEOLOCATE),
        (project(coordinates=None, type_id=1), SurveyTally(), GeolocationStatus.UNCLASSIFIED),
    ],
    ids=[
        "a no-geolocation reason excludes the project",
        "reason zero means no reason",
        "a positioned project without survey is geolocated",
        "a positioned project with all surveys handled is geolocated",
        "a positioned project with pending surveys has surveys to geolocate",
        "a project without position is to geolocate",
        "a survey-driven type ignores the project position",
        "a survey-driven type with pending surveys has surveys to geolocate",
        "a survey-driven type without survey is unclassified",
    ],
)
def test_the_geolocation_status_follows_the_business_rule(subject, tally, status):
    assert classify(subject, tally) is status


@pytest.mark.parametrize(("total", "geolocated"), [(3, 4), (-1, 0), (3, -1)])
def test_an_inconsistent_tally_is_refused(total, geolocated):
    with pytest.raises(ValueError):
        SurveyTally(total, geolocated)


def test_filter_four_gathers_excluded_and_unclassified_projects():
    assert GeolocationFilter.IMPOSSIBLE.matches(GeolocationStatus.EXCLUDED)
    assert GeolocationFilter.IMPOSSIBLE.matches(GeolocationStatus.UNCLASSIFIED)
    assert not GeolocationFilter.IMPOSSIBLE.matches(GeolocationStatus.TO_GEOLOCATE)


def test_an_empty_search_takes_the_default_values():
    assert search_criteria({}) == SearchCriteria()


@pytest.mark.parametrize("value", ["", "   ", "undefined", "null"])
def test_a_value_meaning_absence_filters_nothing(value):
    assert search_criteria({"name": value}).name is None


def test_spaces_around_a_useful_value_are_removed():
    assert search_criteria({"city": "  Albi "}).city == "Albi"


def test_offset_and_limit_are_bounded_instead_of_failing():
    assert search_criteria({"offset": "-100"}).offset == 0
    assert search_criteria({"limit": "0"}).limit == 1
    assert search_criteria({"limit": "5000"}).limit == 1000
    assert search_criteria({"limit": "abc"}).limit == 1


def test_filter_codes_are_read_and_unknown_codes_ignored():
    criteria = search_criteria({"selectedGeo": "3", "selectedSurvey": "2", "selectedGeds": "1"})

    assert (criteria.geolocation_filter, criteria.survey_filter, criteria.ged_filter) == (
        GeolocationFilter.SURVEYS_TO_GEOLOCATE,
        SurveyPresenceFilter.WITHOUT_SURVEYS,
        GedFilter.WITH_DOCUMENTS,
    )
    assert search_criteria({"selectedGeo": "9"}).geolocation_filter is None


def test_without_paginate_skips_the_total():
    assert search_criteria({"withoutPaginate": "1"}).count_total is False


def test_sort_column_and_direction_are_read():
    criteria = search_criteria({"sort": "businessCode", "order": "desc"})

    assert (criteria.sort, criteria.descending) == ("businessCode", True)


@pytest.mark.parametrize(
    "query", [{"sort": "p.id; DROP TABLE projects"}, {"sort": "city_agency"}, {"sort": "name", "order": "random"}]
)
def test_a_sort_outside_the_closed_list_is_refused(query):
    with pytest.raises(InvalidRequest):
        search_criteria(query)


@pytest.mark.parametrize("name", ["", "  ", "SC/1", "S'1", "_S1", "A" * 41])
def test_an_empty_or_special_survey_name_is_refused(name):
    with pytest.raises(InvalidRequest):
        survey_name(name)


def test_a_survey_name_is_trimmed_and_may_hold_accents_spaces_and_separators():
    assert survey_name(" Sondé 1_b.2-c ") == "Sondé 1_b.2-c"


def test_a_new_survey_joins_the_nearest_site():
    sites = [Site("A-1_1", Coordinates(2.30, 48.85)), Site("A-1_2", Coordinates(2.53, 50.73))]

    assert nearest_site(sites, Coordinates(2.5278, 50.7343)).id == "A-1_2"


def test_a_site_without_position_is_kept_only_when_no_site_has_one():
    assert nearest_site([Site("A-1_1", None)], PARIS).id == "A-1_1"
    assert nearest_site([Site("A-1_1", None), Site("A-1_2", PARIS)], PARIS).id == "A-1_2"
    assert nearest_site([], PARIS) is None


@pytest.mark.parametrize(("longitude", "latitude"), [(None, 48.0), (2.0, None), (0.0, 0.0), (2.0, 0.0)])
def test_a_missing_or_zero_position_means_no_position(longitude, latitude):
    assert coordinates_from_geolocation(longitude, latitude) is None


def test_an_out_of_bounds_position_is_refused():
    with pytest.raises(InvalidRequest, match="Longitude hors bornes : 200.000000"):
        coordinates_from_geolocation(200.0, 48.0)


@pytest.mark.parametrize(("value", "expected"), [("12", 12), ("12abc", 12), ("abc", 0), (" -3", -3), (4.9, 4), (True, 1)])
def test_integers_are_read_like_php(value, expected):
    assert php_int(value) == expected


@pytest.mark.parametrize(("value", "expected"), [("45.2", 45.2), ("abc", 0.0), (3, 3.0), ("1e2", 100.0)])
def test_floats_are_read_like_php(value, expected):
    assert php_float(value) == expected
