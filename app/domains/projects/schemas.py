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
    Site,
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


@dataclass(frozen=True)
class GedPresence:
    present: bool
    no_docs_reason_id: int | None = None


# Corps de PATCH /projects/…/ged-presence : { "IsDocGed": true | false, "NoDocsGedReasonID": id | null }.
# Le motif (table no_docs_ged_reasons) précise un « non » : documents introuvables, sans suite…
def ged_presence(payload: dict[str, Any]) -> GedPresence:
    present = payload.get("IsDocGed")

    if not isinstance(present, bool):
        raise InvalidRequest("IsDocGed booléen attendu.")

    reason = payload.get("NoDocsGedReasonID")

    if reason is None:
        return GedPresence(present)

    if isinstance(reason, bool) or not isinstance(reason, int):
        raise InvalidRequest("NoDocsGedReasonID entier attendu.")

    if present:
        raise InvalidRequest("NoDocsGedReasonID n'accompagne qu'une absence de documents.")

    return GedPresence(present, reason)


# Corps de PUT /sites/…/position : { "longitude", "latitude", "altitude" }, chacun nombre ou null ;
# longitude et latitude vont ensemble.
@dataclass(frozen=True)
class SitePosition:
    coordinates: Coordinates | None
    altitude: float | None


def site_position(payload: dict[str, Any]) -> SitePosition:
    for name in ("longitude", "latitude", "altitude"):
        if name not in payload:
            raise InvalidRequest(f"{name} attendu (nombre ou null).")
        if payload[name] is not None and not is_number(payload[name]):
            raise InvalidRequest(f"{name} numérique attendu.")

    longitude, latitude, altitude = payload["longitude"], payload["latitude"], payload["altitude"]

    if (longitude is None) != (latitude is None):
        raise InvalidRequest("longitude et latitude vont ensemble.")

    coordinates = None if longitude is None else coordinates_of(float(longitude), float(latitude))
    return SitePosition(coordinates, None if altitude is None else float(altitude))


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
        "NoDocsGedReasonID": project.no_docs_ged_reason_id,
        "NoDocsGedReason": project.no_docs_ged_reason or "",
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


def site_json(site: Site) -> dict[str, Any]:
    coordinates = site.coordinates
    return {
        "id": site.id,
        "longitude": None if coordinates is None else coordinates.longitude,
        "latitude": None if coordinates is None else coordinates.latitude,
        "altitude": site.altitude,
        "surveyCount": site.survey_count,
    }
