# Routes du socle : paramétrage, statistiques, zones à accès restreint, identité de l'appelant,
# images d'attente. Protégées par le jeton (branchées avec dependencies=protected dans main.py).
# Mêmes URL et mêmes réponses que le back Symfony (ADR-0034 du front). /maj-parametrage n'est pas
# reprise : elle ne servait qu'à l'ancien front.

import re
from typing import Any

from fastapi import APIRouter, Depends, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.core.auth import current_user
from app.core.body import json_object
from app.domains.socle import services, sources
from app.domains.socle.entities import WaitingImage

router = APIRouter(tags=["Socle"])

NUMBER = re.compile(r"\s*([+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?)")


@router.get("/parametrage")
def parametrage() -> dict[str, Any]:
    setting = services.current_setting()
    return {
        "Email": setting.email if setting else "",
        "Message": setting.message if setting else "",
        "Horodatage": _date(setting.recorded_at) if setting else None,
        "UrlManuelUtilisateur": setting.user_manual_url if setting else "",
    }


@router.put("/ajout-statistique-visite")
def record_visit(payload: dict[str, Any] = Depends(json_object), email: str = Depends(current_user)) -> Any:
    if payload.get("Libelle") is None:
        return JSONResponse({"errors": "Libelle absent."}, status_code=400)

    label = _text(payload["Libelle"])
    service_code, recorded_at = services.record_visit(label, email)
    return {"Libelle": label, "ServiceCode": service_code or "", "UserEmail": email, "Horodatage": _date(recorded_at)}


@router.post("/add-address-search-tracing")
def record_address_search(payload: dict[str, Any] = Depends(json_object), email: str = Depends(current_user)) -> Any:
    if payload.get("DepartmentCode") is None:
        return JSONResponse({"errors": "DepartmentCode absent."}, status_code=400)

    tracing = services.record_address_search(
        _text(payload["DepartmentCode"]),
        _text(payload.get("Libelle", "")),
        _number(payload.get("Longitude", 0.0)),
        _number(payload.get("Latitude", 0.0)),
        email,
    )
    return {
        "ID": tracing.id,
        "UserServiceCode": tracing.agency_code or "",
        "UserServiceName": tracing.agency_label or "",
        "ResearchDepartmentCode": tracing.department_code,
        "ResearchServiceCode": tracing.covering_codes or "",
        "ResearchServiceName": tracing.covering_labels or "",
        "IsAuthorized": tracing.authorized,
        "Longitude": tracing.longitude,
        "Latitude": tracing.latitude,
        "Horodatage": _date(tracing.recorded_at),
    }


@router.get("/access-limited-zones")
def access_limited_zones() -> list[dict[str, Any]]:
    return [
        {"ID": zone.id, "Description": zone.description, "Latitude": zone.latitude, "Longitude": zone.longitude, "ZoneKm": zone.radius_kilometers}
        for zone in services.access_limited_zones()
    ]


# L'adresse de l'agent connecté, en chaîne JSON.
@router.get("/about")
def about(email: str = Depends(current_user)) -> str:
    return email


@router.get("/waitingImage/")
def waiting_images() -> list[dict[str, Any]]:
    return [_image(image) for image in services.waiting_images()]


# Une image active tirée au hasard, ou null.
@router.get("/waitingImage/random")
def random_waiting_image() -> dict[str, Any] | None:
    image = services.random_waiting_image()
    return _image(image) if image else None


@router.post("/waitingImage/upload")
async def upload_waiting_image(file: UploadFile | None = None) -> Any:
    if file is None:
        return JSONResponse({"errors": "Aucun fichier recu."}, status_code=400)

    return _image(services.upload_waiting_image(file.filename or "", await file.read()))


@router.put("/waitingImage/{image_id}/activate")
def activate(image_id: int) -> Response:
    return _switched(services.switch_waiting_image(image_id, True))


@router.put("/waitingImage/{image_id}/deactivate")
def deactivate(image_id: int) -> Response:
    return _switched(services.switch_waiting_image(image_id, False))


@router.delete("/waitingImage/{image_id}")
def delete_waiting_image(image_id: int) -> Response:
    return _switched(services.delete_waiting_image(image_id))


# Fichier d'une image, en téléchargement (jamais affiché par le navigateur sous un autre type).
@router.get("/file/waitingImages/{name}")
def waiting_image_file(name: str) -> Response:
    path = sources.absolute_path(name)

    if not path.is_file():
        return Response(status_code=404)

    return FileResponse(path, filename=path.name, headers={"X-Content-Type-Options": "nosniff"})


def _switched(found: bool) -> Response:
    return Response(status_code=204) if found else JSONResponse({"error": "Illustration non trouvee"}, status_code=404)


def _image(image: WaitingImage) -> dict[str, Any]:
    return {"ID": image.id, "Path": image.path, "Active": image.active}


def _date(value) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


# Conversions de l'ancien contrat, à la manière des casts (string) et (float) de PHP.
def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else ""

    return value if isinstance(value, str) else str(value)


def _number(value: Any) -> float:
    if isinstance(value, bool | int | float):
        return float(value)

    match = NUMBER.match(str(value))
    return float(match.group(1)) if match else 0.0
