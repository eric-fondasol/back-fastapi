# Routes de l'administration : /admin/… (docs/features/admin.md du front, ADR-0060).
# Toutes exigent le rôle admin (admin_profile, 403 sinon), en plus du jeton vérifié par main.py.

from typing import Any

from fastapi import APIRouter, Depends, Query, Response

from app.core.body import json_object
from app.core.profile import Profile, admin_profile
from app.domains.admin import services

router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(admin_profile)])

NO_CONTENT = 204


@router.get("/users")
def users() -> list[dict[str, Any]]:
    return services.users()


# Corps : { "role": "admin" } pour donner le rôle admin, { "role": "user" } pour le retirer.
@router.put("/users/{user_id}/role")
def change_role(user_id: str, payload: dict = Depends(json_object), caller: Profile = Depends(admin_profile)) -> dict[str, Any]:
    return services.change_role(caller, user_id, payload)


@router.get("/activity")
def activity() -> dict[str, Any]:
    return services.activity()


@router.get("/business-units")
def business_units() -> list[dict[str, Any]]:
    return services.business_units()


@router.get("/business-lines")
def business_lines() -> list[dict[str, Any]]:
    return services.business_lines()


@router.patch("/business-lines/{code}")
def update_business_line(code: str, payload: dict = Depends(json_object)) -> dict[str, Any]:
    return services.update_business_line(code, payload)


@router.get("/layer-categories")
def layer_categories() -> list[dict[str, Any]]:
    return services.layer_categories()


@router.post("/layer-categories", status_code=201)
def create_layer_category(payload: dict = Depends(json_object), caller: Profile = Depends(admin_profile)) -> dict[str, Any]:
    return services.create_layer_category(caller, payload)


# Déclarée avant /layer-categories/{code} : « order » n'est pas un code de catégorie.
@router.put("/layer-categories/order")
def reorder_layer_categories(payload: dict = Depends(json_object), caller: Profile = Depends(admin_profile)) -> list[dict[str, Any]]:
    return services.reorder_layer_categories(caller, payload)


@router.patch("/layer-categories/{code}")
def update_layer_category(code: str, payload: dict = Depends(json_object), caller: Profile = Depends(admin_profile)) -> dict[str, Any]:
    return services.update_layer_category(caller, code, payload)


@router.delete("/layer-categories/{code}", status_code=NO_CONTENT)
def delete_layer_category(code: str) -> Response:
    services.delete_layer_category(code)
    return Response(status_code=NO_CONTENT)


@router.get("/catalog-layers")
def catalog_layers() -> list[dict[str, Any]]:
    return services.catalog_layers()


@router.patch("/catalog-layers/{code}")
def update_catalog_layer(code: str, payload: dict = Depends(json_object), caller: Profile = Depends(admin_profile)) -> dict[str, Any]:
    return services.update_catalog_layer(caller, code, payload)


@router.get("/referentials")
def referentials() -> dict[str, Any]:
    return services.referentials()


# Explorateur de la base, en lecture seule : tables du schéma public, puis une page de lignes.
@router.get("/database/tables")
def database_tables() -> list[dict[str, Any]]:
    return services.database_tables()


@router.get("/database/tables/{table}")
def table_page(table: str, limit: str | None = Query(None), offset: str | None = Query(None)) -> dict[str, Any]:
    return services.table_page(table, limit, offset)
