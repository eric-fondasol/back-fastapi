# Le métier des affaires : recherche, fiche, sondages, repositionnement et ajout de sondage.
# Repris des handlers Affaires du back Symfony. Chaque fonction ouvre une transaction.

from dataclasses import replace
from datetime import UTC, datetime

from app.core.errors import Conflict, NotFound, Unprocessable
from app.database.connection import refonte_transaction
from app.domains.projects import queries, sources
from app.domains.projects.entities import (
    PROJECT_SURVEYS_LIMIT,
    GeolocationStatus,
    Project,
    SearchCriteria,
    Survey,
    SurveyTally,
    classify,
    nearest_site,
)
from app.domains.projects.schemas import PositionChange, SurveyAddition
from app.domains.projects.sources import GedResponse

REFERENCE_TABLES = {
    "project-types": "project_types",
    "no-geo-project-reasons": "no_geo_project_reasons",
    "no-geo-survey-reasons": "no_geo_survey_reasons",
}


# Colonnes updated_at sans fuseau et à la seconde : on y écrit l'heure UTC, tronquée.
def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0, tzinfo=None)


def search(criteria: SearchCriteria) -> tuple[list[tuple[Project, SurveyTally, GeolocationStatus]], int]:
    with refonte_transaction() as connection:
        found, total = queries.search(connection, criteria)

    return [(project, tally, classify(project, tally)) for project, tally in found], total


def geolocation_statuses(ids: list[str]) -> dict[str, GeolocationStatus]:
    with refonte_transaction() as connection:
        found = queries.projects_with_tallies(connection, ids)

    return {project.id: classify(project, tally) for project, tally in found}


def project(project_id: str) -> Project:
    with refonte_transaction() as connection:
        return _existing_project(connection, project_id)


# La fiche et le nombre de ses chantiers : une affaire sans chantier ne peut pas recevoir de sondage.
def project_with_site_count(project_id: str) -> tuple[Project, int]:
    with refonte_transaction() as connection:
        found = _existing_project(connection, project_id)
        return found, len(queries.project_sites(connection, project_id))


def project_surveys(project_id: str) -> list[Survey]:
    with refonte_transaction() as connection:
        _existing_project(connection, project_id)
        return queries.project_surveys(connection, project_id, PROJECT_SURVEYS_LIMIT)


# Une position remet à zéro le motif de non-géolocalisation et déplace tous les chantiers de
# l'affaire ; sans position, un motif marque l'affaire non géolocalisable.
def relocate_project(project_id: str, change: PositionChange) -> Project:
    with refonte_transaction() as connection:
        relocated = _relocated(_existing_project(connection, project_id), change)

        if change.coordinates is not None:
            queries.relocate_project_sites(connection, project_id, change.coordinates)

        queries.update_project(connection, relocated)
        return relocated


def relocate_survey(survey_id: str, change: PositionChange) -> Survey:
    with refonte_transaction() as connection:
        survey = queries.find_survey(connection, survey_id)

        if survey is None:
            raise NotFound(f"Sondage introuvable : {survey_id}")

        relocated = _relocated(survey, change)
        queries.update_survey(connection, relocated)
        return relocated


# Présence de documents GED déclarée par un utilisateur : écrase la valeur du script de la GED.
def set_ged_presence(project_id: str, present: bool, username: str) -> Project:
    with refonte_transaction() as connection:
        changed = replace(
            _existing_project(connection, project_id), is_doc_ged=present, is_doc_ged_updated_by=username, is_doc_ged_updated_at=_now()
        )
        queries.update_ged_presence(connection, changed)
        return changed


# Le sondage rejoint le chantier de l'affaire le plus proche, sous l'identifiant « <affaire>_<nom> ».
def add_survey(project_id: str, addition: SurveyAddition) -> Survey:
    with refonte_transaction() as connection:
        _existing_project(connection, project_id)
        site = nearest_site(queries.project_sites(connection, project_id), addition.coordinates)

        if site is None:
            raise Unprocessable(f"L'affaire {project_id} n'a pas de chantier.")

        survey_id = f"{project_id}_{addition.name}"

        if queries.find_survey(connection, survey_id) is not None:
            raise Conflict(f"Le sondage {survey_id} existe déjà.")

        survey = Survey(survey_id, site.id, addition.coordinates, altitude=addition.altitude, updated_at=_now())
        queries.insert_survey(connection, survey)
        return survey


# Fiche GED d'une affaire, désignée par son identifiant GED (externe_id) : la GED, elle, est
# interrogée avec le numéro de l'affaire.
def case_detail(externe_id: str) -> GedResponse:
    with refonte_transaction() as connection:
        found = queries.find_project_by_externe_id(connection, externe_id)

    if found is None:
        raise NotFound(f"Affaire introuvable : {externe_id}")

    return sources.case_detail(found.id)


def case_file(project_number: str, file_name: str) -> GedResponse:
    return sources.case_file(project_number, file_name)


def distinct_values(column: str) -> list[str]:
    with refonte_transaction() as connection:
        return queries.distinct_values(connection, column)


def labels(reference: str) -> list[tuple[int, str]]:
    with refonte_transaction() as connection:
        return queries.labels(connection, REFERENCE_TABLES[reference])


def _existing_project(connection, project_id: str) -> Project:
    found = queries.find_project(connection, project_id)

    if found is None:
        raise NotFound(f"Affaire introuvable : {project_id}")

    return found


def _relocated(item, change: PositionChange):
    if change.coordinates is not None:
        item = replace(item, coordinates=change.coordinates, no_geo_reason_id=None, updated_at=_now())
    elif change.no_geo_reason_id is not None:
        item = replace(item, no_geo_reason_id=change.no_geo_reason_id, updated_at=_now())

    if change.altitude is not None:
        item = replace(item, altitude=change.altitude, updated_at=_now())

    return item
