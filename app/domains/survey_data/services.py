# Logique du domaine survey_data : listes de référence, niveaux d'un site, données saisies d'un sondage.

from datetime import date
from typing import Any

from app.core.errors import NotFound, Unprocessable
from app.core.profile import Profile
from app.database.connection import refonte_transaction
from app.domains.survey_data import queries, survey_queries
from app.domains.survey_data.entities import (
    PenetrometerMachineType,
    Referentiel,
    SiteReferenceLevels,
    Standard,
    checked_structures,
    ground_elevation_from_json,
    structures_from_json,
)
from app.domains.survey_data.survey_entities import SavedSurveyData, survey_data_from_json
from app.domains.survey_data.survey_rules import survey_data_errors


def referentiels() -> list[Referentiel]:
    with refonte_transaction() as connection:
        return queries.referentiels(connection)


def standards() -> list[Standard]:
    with refonte_transaction() as connection:
        return queries.standards(connection)


def penetrometer_machine_types() -> list[PenetrometerMachineType]:
    with refonte_transaction() as connection:
        return queries.penetrometer_machine_types(connection)


def site_reference_levels(site_id: str) -> SiteReferenceLevels:
    with refonte_transaction() as connection:
        return _site_levels(connection, site_id)


# Forme du corps vérifiée avant toute lecture (400), règles métier ensuite (422), site inconnu : 404.
# Une cote du terrain naturel différente devient l'altitude du site, tracée dans l'historique.
def replace_site_reference_levels(site_id: str, payload: dict[str, Any], author: Profile) -> SiteReferenceLevels:
    structures = structures_from_json(payload)
    ground_elevation = ground_elevation_from_json(payload)
    with refonte_transaction() as connection:
        current = _site_levels(connection, site_id)
        standard_ids = {standard.id for standard in queries.standards(connection)}
        referentiel_codes = {referentiel.code for referentiel in queries.referentiels(connection)}
        queries.replace_site_structures(connection, site_id, checked_structures(structures, standard_ids, referentiel_codes))
        if ground_elevation.provided and ground_elevation.value != current.ground_elevation:
            queries.record_site_position(connection, site_id, author.id, author.email)
            queries.update_site_altitude(connection, site_id, ground_elevation.value)
        return _site_levels(connection, site_id)


def _site_levels(connection, site_id: str) -> SiteReferenceLevels:
    found, altitude = queries.site_altitude(connection, site_id)
    if not found:
        raise NotFound(f"Site introuvable : {site_id}")
    return SiteReferenceLevels(site_id=site_id, ground_elevation=altitude, structures=queries.site_structures(connection, site_id))


def survey_data(survey_id: str) -> SavedSurveyData:
    with refonte_transaction() as connection:
        survey = _existing_survey(connection, survey_id)
        return SavedSurveyData(survey_id=survey.id, ground_elevation=survey.altitude, data=survey_queries.read_survey_data(connection, survey.id))


# Forme du corps (400), sondage inconnu (404), règles métier (422, tous les messages réunis) ; puis chaque
# section remplace les lignes du sondage. Une cote du terrain naturel différente devient l'altitude du
# sondage, tracée dans l'historique de géolocalisation.
def replace_survey_data(survey_id: str, payload: dict[str, Any], author: Profile, today: date) -> SavedSurveyData:
    data = survey_data_from_json(payload)
    ground_elevation = ground_elevation_from_json(payload)
    with refonte_transaction() as connection:
        survey = _existing_survey(connection, survey_id)
        standard_ids = {standard.id for standard in queries.standards(connection)}
        referentiel_codes = {referentiel.code for referentiel in queries.referentiels(connection)}
        machine_types = survey_queries.machine_types(connection)
        errors = survey_data_errors(data, standard_ids, referentiel_codes, set(machine_types), today)
        if errors:
            raise Unprocessable(" ".join(errors))

        machine_type_id = None if data.penetrometer is None else data.penetrometer.machine_type_id
        survey_queries.replace_survey_data(connection, survey, data, machine_types.get(machine_type_id) if machine_type_id is not None else None)
        if ground_elevation.provided and ground_elevation.value != survey.altitude:
            survey_queries.record_survey_position(connection, survey.id, author.id, author.email)
            survey_queries.update_survey_altitude(connection, survey.id, ground_elevation.value)

        refreshed = _existing_survey(connection, survey.id)
        return SavedSurveyData(survey_id=refreshed.id, ground_elevation=refreshed.altitude, data=survey_queries.read_survey_data(connection, survey.id))


def _existing_survey(connection, survey_id: str) -> survey_queries.SurveyRow:
    survey = survey_queries.find_survey(connection, survey_id)
    if survey is None:
        raise NotFound(f"Sondage introuvable : {survey_id}")
    return survey
