# Route des rapports archivés : GET /reports?projects=N1|N2|… renvoie une archive ZIP.
# Protégée par le jeton (branchée avec dependencies=protected dans main.py).

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.domains.reports import services
from app.domains.reports.entities import archive_path
from app.domains.reports.sources import ReportArchiveUnavailable

router = APIRouter(tags=["Reports"])


@router.get("/reports")
def reports(request: Request) -> Response:
    projects = [archive_path(number) for number in request.query_params.get("projects", "").split("|") if number.strip()]

    if not projects:
        return JSONResponse("No projects selected", status_code=400)

    try:
        content = services.archive(projects)
    except ReportArchiveUnavailable:
        return JSONResponse({"error": "depot de rapports injoignable"}, status_code=502)

    return Response(content, media_type="application/zip")
