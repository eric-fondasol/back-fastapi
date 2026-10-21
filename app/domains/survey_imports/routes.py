# Route de lecture d'un classeur Excel de sondages : POST /survey-imports/workbook (multipart,
# champ « file »). Contrat attendu par le front (docs/features/map.md, US-CARTE-26).
# Protégée par le jeton (branchée avec dependencies=protected dans main.py).

from typing import Any

from fastapi import APIRouter, UploadFile

from app.core.errors import InvalidRequest
from app.domains.survey_imports import services

router = APIRouter(tags=["Survey imports"])


# { "sheets": [ { "name": "Sondages", "rows": [["Nom", "Latitude", …], …], "truncated": false } ] }
@router.post("/survey-imports/workbook")
async def read_workbook(file: UploadFile | None = None) -> dict[str, Any]:
    if file is None:
        raise InvalidRequest("Aucun fichier reçu (champ « file »).")

    content = await file.read(services.MAX_WORKBOOK_BYTES + 1)
    sheets = services.read_workbook(file.filename or "", content)
    return {"sheets": [{"name": sheet.name, "rows": sheet.rows, "truncated": sheet.truncated} for sheet in sheets]}
