# Le contrat des routes des affaires, repris tel quel de l'ancien back Go puis Symfony :
# champs en PascalCase (« ID », « NbSurveysGeoloc »…), valeurs absentes rendues par "" ou 0.
# - lecture des corps envoyés par le front (position, ajout de sondage, liste d'affaires) ;
# - mise en forme des réponses (affaire, sondage, référentiel).
# Le contrôle est fait ici plutôt que par Pydantic, pour garder les codes et messages d'origine.

import base64
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.errors import InvalidRequest
from app.domains.projects.entities import (
    MAX_STATUS_PROJECTS,
    Coordinates,
    GeolocationStatus,
    Project,
    Survey,
    SurveyTally,
    coordinates_from_geolocation,
    coordinates_of,
    is_number,
    php_float,
    php_int,
    survey_name,
)

MAX_PROJECT_ID_LENGTH = 64


# Changement de position d'une affaire ou d'un sondage (PUT /projects/… et /surveys/…).
@dataclass(frozen=True)
class PositionChange:
    coordinates: Coordinates | None
    no_geo_reason_id: int | None
    altitude: float | None


@dataclass(frozen=True)
class SurveyAddition:
    name: str
    coordinates: Coordinates
    altitude: float | None


# Corps de PATCH /projects/…/ged-presence : { "IsDocGed": true | false }.
def ged_presence(payload: dict[str, Any]) -> bool:
    present = payload.get("IsDocGed")

    if not isinstance(present, bool):
        raise InvalidRequest("IsDocGed booléen attendu.")

    return present


# L'identifiant arrive encodé en base64 dans l'URL : il peut contenir « / » ou une apostrophe.
def decoded_id(encoded: str) -> str:
    try:
        decoded = base64.b64decode(encoded + "=" * (-len(encoded) % 4), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        decoded = ""

    if not decoded:
        raise InvalidRequest("Identifiant base64 invalide.")

    return decoded


# Une position absente (ou à zéro) n'efface rien : seul le motif de non-géolocalisation, puis
# l'altitude, sont alors pris en compte.
def position_change(payload: dict[str, Any], reason_field: str) -> PositionChange:
    coordinates = None

    if payload.get("Latitude") is not None and payload.get("Longitude") is not None:
        coordinates = coordinates_from_geolocation(php_float(payload["Longitude"]), php_float(payload["Latitude"]))

    reason = payload.get(reason_field)
    return PositionChange(coordinates, None if reason is None else php_int(reason), _altitude(payload))


def survey_addition(payload: dict[str, Any]) -> SurveyAddition:
    if not isinstance(payload.get("Name"), str):
        raise InvalidRequest("Nom de sondage attendu.")

    for name in ("Latitude", "Longitude"):
        if not is_number(payload.get(name)):
            raise InvalidRequest(f"{name} numérique attendue.")

    return SurveyAddition(
        survey_name(payload["Name"]),
        coordinates_of(float(payload["Longitude"]), float(payload["Latitude"])),
        _altitude(payload),
    )


def project_ids(payload: dict[str, Any]) -> list[str]:
    ids = payload.get("ids")

    if not isinstance(ids, list) or len(ids) > MAX_STATUS_PROJECTS:
        raise InvalidRequest(f"ids : liste de {MAX_STATUS_PROJECTS} numéros d'affaire au plus.")

    for project_id in ids:
        if not isinstance(project_id, str) or not project_id.strip() or len(project_id) > MAX_PROJECT_ID_LENGTH:
            raise InvalidRequest("ids : chaque numéro d'affaire est une chaîne non vide.")

    return ids


def _altitude(payload: dict[str, Any]) -> float | None:
    altitude = payload.get("Altitude")

    if altitude is None:
        return None

    if not is_number(altitude):
        raise InvalidRequest("Altitude numérique attendue.")

    return float(altitude)


# Le statut de géolocalisation n'est connu qu'avec le décompte des sondages (recherche) ; sans lui
# il vaut null plutôt que d'être deviné.
def project_json(project: Project, tally: SurveyTally | None = None, status: GeolocationStatus | None = None) -> dict[str, Any]:
    tally = tally or SurveyTally()
    coordinates, entered = project.coordinates, project.entered_position
    return {
        "ID": project.id,
        "Name": project.name or "",
        "City": project.city or "",
        "Latitude": coordinates.latitude if coordinates else 0.0,
        "Longitude": coordinates.longitude if coordinates else 0.0,
        "Altitude": project.altitude if project.altitude is not None else 0.0,
        "NoGeoProjectReasonID": project.no_geo_reason_id,
        "ProjectTypeID": project.type_id or 0,
        "CityAgency": project.city_agency or "",
        "CodeMetier": project.code_metier or "",
        "Client": project.client or "",
        "UUID": project.uuid or "",
        "ExterneId": project.externe_id or "",
        "UrlID": project.url_id or "",
        "IsDocGed": project.is_doc_ged,
        "IsDocGedUpdatedBy": project.is_doc_ged_updated_by or "",
        "IsDocGedUpdatedAt": _date(project.is_doc_ged_updated_at),
        "UserEmail": project.user_email or "",
        "SystemeGeo": entered.geodetic_system or "",
        "LatitudeSaisie": entered.latitude if entered.latitude is not None else 0.0,
        "LongitudeSaisie": entered.longitude if entered.longitude is not None else 0.0,
        "NbSurveys": tally.total,
        "NbSurveysGeoloc": tally.geolocated,
        "GeolocationStatus": status.value if status else None,
        "UpdatedAt": _date(project.updated_at),
    }


# Fiche d'une affaire (GET /projects/{numéro}) : avec le nombre de ses chantiers, que la liste n'a pas.
def project_sheet_json(project: Project, site_count: int) -> dict[str, Any]:
    return project_json(project) | {"SiteCount": site_count}


# Pressions et lithologies restent vides, comme dans l'ancien contrat.
def survey_json(survey: Survey) -> dict[str, Any]:
    coordinates, entered = survey.coordinates, survey.entered_position
    return {
        "ID": survey.id,
        "SiteID": survey.site_id,
        "Latitude": coordinates.latitude if coordinates else 0.0,
        "Longitude": coordinates.longitude if coordinates else 0.0,
        "City": survey.city or "",
        "Altitude": survey.altitude if survey.altitude is not None else 0.0,
        "DepthMin": survey.depth_min if survey.depth_min is not None else 0.0,
        "DepthMax": survey.depth_max if survey.depth_max is not None else 0.0,
        "NoGeoSurveyReasonID": survey.no_geo_reason_id or 0,
        "SystemeGeo": entered.geodetic_system or "",
        "LatitudeSaisie": entered.latitude if entered.latitude is not None else 0.0,
        "LongitudeSaisie": entered.longitude if entered.longitude is not None else 0.0,
        "UpdatedAt": _date(survey.updated_at),
        "Pressures": [],
        "Lithologies": [],
    }


def label_json(label: tuple[int, str]) -> dict[str, Any]:
    return {"ID": label[0], "Libelle": label[1]}


# Les dates sont stockées sans fuseau, en UTC : rendues au format RFC 3339 (« …+00:00 »).
def _date(value: datetime | None) -> str | None:
    return value.replace(tzinfo=UTC).isoformat(timespec="seconds") if value else None
