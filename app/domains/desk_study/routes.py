# Routes de l'enquête documentaire servies par l'ancien back : planches (POST et catalogue) et
# relais des fiches Infoterre du BRGM. Protégées par le jeton (dependencies=protected dans main.py).
# Mêmes URL et mêmes réponses que le back Symfony (ADR-0034 du front).

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.body import json_object
from app.core.errors import DomainError, InvalidRequest
from app.domains.desk_study import sources
from app.domains.desk_study.entities import trusted_infoterre_url

router = APIRouter(tags=["Desk study"])


# 200 si toutes les planches ont abouti, 207 si l'une au moins est dégradée ou indisponible.
@router.post("/api/enquetes/planches")
async def planches(payload: dict[str, Any] = Depends(json_object)) -> JSONResponse:
    longitude, latitude = payload.get("longitude"), payload.get("latitude")

    if longitude is None or latitude is None:
        return JSONResponse({"error": "longitude et latitude sont requis"}, status_code=400)

    longitude, latitude = _coordinate(longitude), _coordinate(latitude)

    if not -180 <= longitude <= 180:
        raise InvalidRequest(f"Longitude hors bornes : {longitude:f}")
    if not -90 <= latitude <= 90:
        raise InvalidRequest(f"Latitude hors bornes : {latitude:f}")

    requested = payload.get("planches") or list(sources.CATALOGUE)
    results = await sources.fetch_planches([str(name) for name in requested], longitude, latitude, payload.get("codeInsee"))
    body = {
        "position": {"longitude": longitude, "latitude": latitude},
        "planches": {name: result.to_json() for name, result in results.items()},
    }
    return JSONResponse(body, status_code=200 if all(result.usable for result in results.values()) else 207)


@router.get("/api/enquetes/planches")
def catalogue() -> dict[str, list[str]]:
    return {"planches": list(sources.CATALOGUE)}


# Le contenu relayé est neutralisé (pas d'interprétation du type, pas de script, pas de ressource
# chargée) : il vient d'un tiers.
@router.get("/infoterre")
def infoterre(request: Request) -> Any:
    url = request.query_params.get("infoterreUrl")

    if not url:
        return JSONResponse("No infoterreUrl param", status_code=400)

    try:
        content = sources.fetch_external(trusted_infoterre_url(url))
    except DomainError as refusal:
        return JSONResponse({"message": str(refusal)}, status_code=refusal.status_code)
    except sources.ExternalContentUnavailable as error:
        return JSONResponse({"message": str(error)}, status_code=502)

    return StreamingResponse(
        content.body,
        status_code=content.status_code,
        headers={
            "Content-Type": content.content_type,
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


def _coordinate(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise InvalidRequest("longitude et latitude doivent etre des nombres") from None
