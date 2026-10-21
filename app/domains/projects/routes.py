# Routes des affaires, sondages et référentiels de l'écran Projets et de l'édition sur la carte.
# Protégées par le jeton (branchées avec dependencies=protected dans main.py).
# Mêmes URL, mêmes réponses et mêmes codes que le back Symfony (ADR-0034 du front).

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.auth import current_user
from app.core.body import json_object
from app.core.errors import InvalidRequest
from app.core.logger import logger
from app.domains.projects import schemas, services
from app.domains.projects.entities import search_criteria
from app.domains.projects.sources import GedResponse, GedUnavailable

router = APIRouter(tags=["Projects"])


# Recherche paginée : { "items": [...], "count": total } ; count vaut 0 avec withoutPaginate=1.
@router.get("/projects")
def search_projects(request: Request) -> dict[str, Any]:
    found, total = services.search(search_criteria(dict(request.query_params)))
    return {"items": [schemas.project_json(project, tally, status) for project, tally, status in found], "count": total}


# Statut de géolocalisation de chaque affaire demandée (1 000 au plus) ; une inconnue est absente.
@router.post("/projects/geolocation-statuses")
def geolocation_statuses(payload: dict[str, Any] = Depends(json_object)) -> dict[str, Any]:
    statuses = services.geolocation_statuses(schemas.project_ids(payload))
    return {"statuses": {project_id: status.value for project_id, status in statuses.items()}}


@router.get("/projects/{project_id:path}/surveys")
def project_surveys(project_id: str) -> list[dict[str, Any]]:
    return [schemas.survey_json(survey) for survey in services.project_surveys(project_id)]


# « :path » : un numéro d'affaire peut contenir « / » (« PR.GT01.25.0082 / DE-16511 »), décodé
# depuis « %2F » avant le routage. Les routes « …/surveys » sont déclarées avant celle de la fiche.
# 201 ; 404 affaire inconnue, 422 affaire sans chantier, 409 sondage déjà présent.
@router.post("/projects/{project_id:path}/surveys", status_code=201)
def add_survey(project_id: str, payload: dict[str, Any] = Depends(json_object)) -> JSONResponse:
    survey = services.add_survey(project_id, schemas.survey_addition(payload))
    return JSONResponse(schemas.survey_json(survey), status_code=201)


# Déclaration manuelle de la présence de documents GED (panneau Détails de l'affaire du front).
# 404 affaire inconnue, 400 corps invalide.
@router.patch("/projects/{project_id:path}/ged-presence")
def set_ged_presence(
    project_id: str, payload: dict[str, Any] = Depends(json_object), username: str = Depends(current_user)
) -> dict[str, Any]:
    return schemas.project_json(services.set_ged_presence(project_id, schemas.ged_presence(payload), username))


@router.get("/projects/{project_id:path}")
def project(project_id: str) -> dict[str, Any]:
    return schemas.project_sheet_json(*services.project_with_site_count(project_id))


# L'identifiant est encodé en base64 dans l'URL ; le base64 peut lui-même contenir « / ».
@router.put("/projects/{encoded_id:path}")
def relocate_project(encoded_id: str, payload: dict[str, Any] = Depends(json_object)) -> dict[str, Any]:
    project_id = schemas.decoded_id(encoded_id)
    return schemas.project_json(services.relocate_project(project_id, schemas.position_change(payload, "NoGeoProjectReasonID")))


@router.put("/surveys/{encoded_id:path}")
def relocate_survey(encoded_id: str, payload: dict[str, Any] = Depends(json_object)) -> dict[str, Any]:
    survey_id = schemas.decoded_id(encoded_id)
    return schemas.survey_json(services.relocate_survey(survey_id, schemas.position_change(payload, "NoGeoSurveyReasonID")))


@router.get("/codes-metier")
def codes_metier() -> list[str]:
    return services.distinct_values("code_metier")


@router.get("/city-agencies")
def city_agencies() -> list[str]:
    return services.distinct_values("city_agency")


@router.get("/project-types")
def project_types() -> list[dict[str, Any]]:
    return [schemas.label_json(label) for label in services.labels("project-types")]


@router.get("/no-geo-project-reasons")
def no_geo_project_reasons() -> list[dict[str, Any]]:
    return [schemas.label_json(label) for label in services.labels("no-geo-project-reasons")]


@router.get("/no-geo-survey-reasons")
def no_geo_survey_reasons() -> list[dict[str, Any]]:
    return [schemas.label_json(label) for label in services.labels("no-geo-survey-reasons")]


# Fiche GED d'une affaire, relayée telle quelle (statut et corps de la GED).
@router.get("/case-detail/{externe_id}")
def case_detail(externe_id: str):
    return _relay(lambda: services.case_detail(externe_id))


# Fichier GED d'une affaire, relayé en flux avec son type, son nom et sa taille.
@router.get("/case-file/{project_number:path}")
def case_file(project_number: str, request: Request):
    file_name = request.query_params.get("file", "")

    if not file_name:
        raise InvalidRequest('Le parametre "file" est requis.')

    return _relay(lambda: services.case_file(project_number, file_name))


# GED injoignable : 502, sans détail (l'adresse interne de la GED ne doit pas sortir).
def _relay(call) -> StreamingResponse | JSONResponse:
    try:
        ged: GedResponse = call()
    except GedUnavailable as error:
        # La raison reste dans le journal (configuration absente, GED muette…), pas dans la réponse.
        logger.error("GED indisponible : %s", error)
        return JSONResponse({"error": "ged injoignable"}, status_code=502)

    return StreamingResponse(ged.body, status_code=ged.status_code, headers=ged.headers)
