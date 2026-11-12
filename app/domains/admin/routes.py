# Routes de l'administration : /admin/… (docs/features/admin.md du front, ADR-0060).
# Toutes exigent le rôle admin (admin_profile, 403 sinon), en plus du jeton vérifié par main.py.

from typing import Any

from fastapi import APIRouter, Depends, Query, Response

from app.core.body import json_object
from app.core.profile import Profile, admin_profile
from app.domains.admin import editing, services

router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(admin_profile)])

NO_CONTENT = 204


@router.get("/activity")
def activity() -> dict[str, Any]:
    return services.activity()


# Explorateur de la base : tables du schéma public, puis une page de lignes. Les tables de
# editing.EDITABLE_TABLES acceptent en plus la création, la modification et la suppression de lignes.
@router.get("/database/tables")
def database_tables() -> list[dict[str, Any]]:
    return services.database_tables()


@router.get("/database/tables/{table}")
def table_page(table: str, limit: str | None = Query(None), offset: str | None = Query(None)) -> dict[str, Any]:
    return services.table_page(table, limit, offset)


# Lignes proposées par une colonne qui pointe vers une autre table : { table, choices: [{ value, label }], truncated }.
@router.get("/database/tables/{table}/columns/{column}/choices")
def column_choices(table: str, column: str) -> dict[str, Any]:
    return services.column_choices(table, column)


@router.get("/database/tables/{table}/row")
def table_row(table: str, key: str | None = Query(None)) -> dict[str, Any]:
    return editing.row(table, key)


@router.post("/database/tables/{table}/rows", status_code=201)
def create_table_row(table: str, payload: dict = Depends(json_object), caller: Profile = Depends(admin_profile)) -> dict[str, Any]:
    return editing.create_row(caller, table, payload)


@router.patch("/database/tables/{table}/rows")
def update_table_row(table: str, payload: dict = Depends(json_object), caller: Profile = Depends(admin_profile)) -> dict[str, Any]:
    return editing.update_row(caller, table, payload)


@router.get("/database/tables/{table}/deletion")
def table_row_deletion(table: str, key: str | None = Query(None)) -> dict[str, Any]:
    return editing.deletion_impact(table, key)


@router.delete("/database/tables/{table}/rows", status_code=NO_CONTENT)
def delete_table_row(table: str, key: str | None = Query(None), caller: Profile = Depends(admin_profile)) -> Response:
    editing.delete_row(caller, table, key)
    return Response(status_code=NO_CONTENT)
