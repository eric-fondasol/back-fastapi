# Routes des enquêtes enregistrées et de leurs versions (ADR-0032 du front) : /investigations/…,
# et la recherche d'enquêtes par n° d'affaire, /saved-page/search (contrat de l'ancien back).
# Protégées par le jeton (branchées avec dependencies=protected dans main.py). L'auteur d'une
# version est l'agent connecté (current_profile), jamais un champ du corps.

import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.core.body import json_object
from app.core.errors import InvalidRequest, NotFound
from app.core.profile import Profile, current_profile
from app.domains.investigations import services
from app.domains.investigations import entities
from app.domains.investigations.entities import DEFAULT_SEARCH_LIMIT, Investigation, Version, text_field

router = APIRouter(tags=["Investigations"])

VERSION_NUMBER = re.compile(r"\d+")
LEADING_INTEGER = re.compile(r"\s*([+-]?\d+)")


# Les enquêtes d'une affaire, chacune avec ses versions (sans leur contenu), la plus récente en tête.
@router.get("/investigations")
def of_project(request: Request) -> list[dict[str, Any]]:
    project_ref = request.query_params.get("projectRef", "").strip()

    if not project_ref:
        raise InvalidRequest("Le parametre projectRef est requis.")

    return [
        _investigation(investigation) | {"versions": [_version(version) for version in versions]}
        for investigation, versions in services.of_project(project_ref)
    ]


# Sondages pressio et pénétro fiables à 1 000 m d'une position, et proposition qui en découle
# (US-INVESTIGATIONS-11 du front). Déclarée avant /investigations/{page_uuid}, qu'elle masquerait sinon.
@router.get("/investigations/fuseau-offer")
def fuseau_offer(request: Request, profile: Profile = Depends(current_profile)) -> dict[str, Any]:
    longitude, latitude = entities.position(request.query_params.get("longitude"), request.query_params.get("latitude"))
    offer = services.fuseau_offer(profile, longitude, latitude)
    return {"surveys": offer.surveys, "offer": offer.offer, "answerRequired": offer.answer_required}


# La dernière version, avec son contenu (« data »).
@router.get("/investigations/{page_uuid}")
def latest(page_uuid: str) -> dict[str, Any]:
    return _with_content(*services.read(_uuid(page_uuid)))


@router.get("/investigations/{page_uuid}/versions/{number}")
def version(page_uuid: str, number: str) -> dict[str, Any]:
    return _with_content(*services.read(_uuid(page_uuid), _number(number)))


# Premier enregistrement : crée l'enquête et sa version 1.
@router.post("/investigations")
def create(payload: dict[str, Any] = Depends(json_object), profile: Profile = Depends(current_profile)) -> JSONResponse:
    saved = services.create(
        profile,
        text_field(payload, "projectRef") or "",
        text_field(payload, "name"),
        text_field(payload, "data") or "",
        text_field(payload, "comment"),
        entities.fuseau_analysis(payload.get("fuseauAnalysis")),
    )
    return JSONResponse(_saved(*saved), status_code=201)


@router.post("/investigations/{page_uuid}/versions")
def add_version(page_uuid: str, payload: dict[str, Any] = Depends(json_object), profile: Profile = Depends(current_profile)) -> JSONResponse:
    saved = services.add_version(
        profile,
        _uuid(page_uuid),
        text_field(payload, "data") or "",
        text_field(payload, "comment"),
        entities.fuseau_analysis(payload.get("fuseauAnalysis")),
    )
    return JSONResponse(_saved(*saved), status_code=201)


# Écrase la dernière version (409 pour une version antérieure).
@router.put("/investigations/{page_uuid}/versions/{number}")
def revise_version(
    page_uuid: str, number: str, payload: dict[str, Any] = Depends(json_object), profile: Profile = Depends(current_profile)
) -> dict[str, Any]:
    saved = services.revise_version(
        profile,
        _uuid(page_uuid),
        _number(number),
        text_field(payload, "data") or "",
        text_field(payload, "comment"),
        entities.fuseau_analysis(payload.get("fuseauAnalysis")),
    )
    return _saved(*saved)


@router.patch("/investigations/{page_uuid}")
def rename(page_uuid: str, payload: dict[str, Any] = Depends(json_object)) -> dict[str, Any]:
    return _investigation(services.rename(_uuid(page_uuid), text_field(payload, "name")))


# Recherche par n° d'affaire ou nom (30 résultats par défaut) ; aucun résultat : 404.
@router.get("/saved-page/search")
def search(request: Request) -> Any:
    found = services.search(request.query_params.get("q"), _limit(request.query_params.get("limit")))

    if not found:
        return JSONResponse({"message": "Aucun SavedPage trouve"}, status_code=404)

    return [
        {
            "uuid": summary.uuid,
            "projectRef": summary.project_ref or "",
            "projectRefCommentaire": summary.name or "",
            "hasCoordinates": summary.has_coordinates,
        }
        for summary in found
    ]


# Un identifiant ou un numéro mal formé ne désigne aucune enquête : 404, comme une route inconnue.
def _uuid(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        parsed = None

    if parsed is None or len(value) != 36:
        raise NotFound(f"Enquete introuvable : {value}")

    return str(parsed)


# Limite lue comme le cast (int) de PHP (« 12abc » vaut 12) ; nulle ou négative : 30.
def _limit(value: str | None) -> int:
    match = LEADING_INTEGER.match(value or "")
    limit = int(match.group(1)) if match else 0
    return limit if limit > 0 else DEFAULT_SEARCH_LIMIT


def _number(value: str) -> int:
    if not VERSION_NUMBER.fullmatch(value):
        raise NotFound(f"Version d'enquete introuvable : {value}")

    return int(value)


def _investigation(investigation: Investigation) -> dict[str, Any]:
    return {
        "uuid": investigation.uuid,
        "projectRef": investigation.project_ref or "",
        "name": investigation.name or "",
        "hasCoordinates": investigation.has_coordinates,
    }


def _version(version: Version) -> dict[str, Any]:
    return {
        "id": version.id,
        "version": version.number,
        "comment": version.comment,
        "author": {"id": version.author.user_id, "name": version.author.name},
        "createdAt": _date(version.created_at),
        "updatedAt": _date(version.updated_at),
    }


def _saved(investigation: Investigation, version: Version) -> dict[str, Any]:
    return _investigation(investigation) | {"latestVersion": version.number, "version": _version(version)}


def _with_content(investigation: Investigation, version: Version, latest: int) -> dict[str, Any]:
    return _investigation(investigation) | {"latestVersion": latest, "version": _version(version) | {"data": version.data}}


def _date(value) -> str | None:
    return value.isoformat(timespec="seconds") if value else None
