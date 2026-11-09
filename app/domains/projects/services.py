# Le métier des affaires : recherche, fiche, sondages, repositionnement et ajout de sondage.
# Repris des handlers Affaires du back Symfony. Chaque fonction ouvre une transaction.

from dataclasses import replace
from datetime import UTC, datetime

from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.profile import Profile
from app.database.connection import refonte_transaction
from app.domains.projects import queries, sources
from app.domains.projects.entities import (
    PROJECT_SURVEYS_LIMIT,
    GeolocationStatus,
    Project,
    SearchCriteria,
    Site,
    Survey,
    SurveyTally,
    classify,
    nearest_site,
)
from app.domains.projects.schemas import GedPresence, PositionChange, SitePosition, SurveyAddition
from app.domains.projects.sources import GedResponse

REFERENCE_TABLES = {
    "project-types": "project_types",
    "no-geo-project-reasons": "no_geo_project_reasons",
    "no-geo-survey-reasons": "no_geo_survey_reasons",
    "no-docs-ged-reasons": "no_docs_ged_reasons",
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
        return found, len(queries.project_sites(connection, found.key))


# Sites (chantiers) d'une affaire, dans la base métier : la carte ne connaît que l'uuid de l'entrepôt,
# le front retrouve ici le site à éditer (données du site, US-CARTE-46).
def project_sites(project_id: str) -> list[Site]:
    with refonte_transaction() as connection:
        found = _existing_project(connection, project_id)
        return queries.project_sites(connection, found.key)


def project_surveys(project_id: str) -> list[Survey]:
    with refonte_transaction() as connection:
        found = _existing_project(connection, project_id)
        return queries.project_surveys(connection, found.key, PROJECT_SURVEYS_LIMIT)


# Une position remet à zéro le motif de non-géolocalisation et déplace tous les chantiers de
# l'affaire ; sans position, un motif marque l'affaire non géolocalisable. Position et altitude sont
# celles des chantiers (schéma v3).
def relocate_project(project_id: str, change: PositionChange, author: Profile) -> Project:
    with refonte_transaction() as connection:
        relocated = _relocated(_existing_project(connection, project_id), change)
        queries.relocate_project_sites(connection, relocated, change.coordinates, change.altitude, author.id, author.email)
        queries.update_project(connection, relocated)
        return relocated


def relocate_survey(survey_id: str, change: PositionChange, author: Profile) -> Survey:
    with refonte_transaction() as connection:
        survey = queries.find_survey(connection, survey_id)

        if survey is None:
            raise NotFound(f"Sondage introuvable : {survey_id}")

        relocated = _relocated(survey, change)
        if change.coordinates is not None or change.altitude is not None:
            queries.record_survey_position(connection, survey_id, author.id, author.email)
        queries.update_survey(connection, relocated)
        return relocated


# Présence de documents GED déclarée par un utilisateur : écrase la valeur du script de la GED.
# Un motif inconnu de no_docs_ged_reasons est refusé (422).
def set_ged_presence(project_id: str, presence: GedPresence, username: str) -> Project:
    with refonte_transaction() as connection:
        found = _existing_project(connection, project_id)
        reason_id = presence.no_docs_reason_id
        if reason_id is not None and not queries.has_no_docs_ged_reason(connection, reason_id):
            raise Unprocessable(f"Motif d'absence de documents GED inconnu : {reason_id}")
        changed = replace(
            found,
            is_doc_ged=presence.present,
            is_doc_ged_updated_by=username,
            is_doc_ged_updated_at=_now(),
            no_docs_ged_reason_id=reason_id,
        )
        queries.update_ged_presence(connection, changed, found.is_doc_ged)
        return queries.find_project(connection, project_id) or changed


# Position et altitude d'un site de l'affaire, remplacées telles que saisies. 404 site inconnu.
def relocate_site(site_id: str, position: SitePosition, author: Profile) -> Site:
    with refonte_transaction() as connection:
        found = queries.find_site(connection, site_id)
        if found is None:
            raise NotFound(f"Site introuvable : {site_id}")
        if found.survey_count > 0:
            raise Conflict(f"Le site {site_id} a des sondages : seul un site sans sondage peut être géolocalisé.")
        relocated = replace(found, coordinates=position.coordinates, altitude=position.altitude)
        queries.relocate_site(connection, relocated, author.id, author.email)
        return relocated


# Le sondage rejoint le chantier de l'affaire le plus proche, sous l'identifiant « <affaire>_<nom> ».
def add_survey(project_id: str, addition: SurveyAddition) -> Survey:
    with refonte_transaction() as connection:
        found = _existing_project(connection, project_id)
        site = nearest_site(queries.project_sites(connection, found.key), addition.coordinates)

        if site is None:
            raise Unprocessable(f"L'affaire {project_id} n'a pas de chantier.")

        survey_id = f"{project_id}_{addition.name}"

        if queries.find_survey(connection, survey_id) is not None:
            raise Conflict(f"Le sondage {survey_id} existe déjà.")

        survey = Survey(survey_id, site.id, addition.coordinates, name=addition.name, altitude=addition.altitude, updated_at=_now())
        queries.insert_survey(connection, survey)
        return survey


# Fiche GED d'une affaire, désignée par son identifiant GED (l'id de l'entrepôt, ancien externe_id) :
# la GED, elle, est interrogée avec le numéro de l'affaire.
def case_detail(externe_id: str) -> GedResponse:
    with refonte_transaction() as connection:
        found = queries.find_project_by_ged_id(connection, externe_id)

    if found is None:
        raise NotFound(f"Affaire introuvable : {externe_id}")

    return sources.case_detail(found.id)


def case_file(project_number: str, file_name: str) -> GedResponse:
    return sources.case_file(project_number, file_name)


def business_codes() -> list[str]:
    with refonte_transaction() as connection:
        return queries.business_codes(connection)


def agencies() -> list[str]:
    with refonte_transaction() as connection:
        return queries.agencies(connection)


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
