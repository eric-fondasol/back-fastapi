# Routes du profil de l'agent connecté : /me, /me/preferences, /me/favorites/…
# Protégées par le jeton (branchées avec dependencies=protected dans main.py). Chaque route agit
# sur le profil de l'appelant (current_profile) : aucun identifiant d'agent dans l'URL.
# Les corps sont contrôlés par entities.py (400 et message du back Symfony), pas par Pydantic.

from typing import Any

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from app.core.auth import Identity, current_identity
from app.core.body import json_object
from app.core.profile import Profile, current_profile, provision
from app.domains.profile import services

router = APIRouter(prefix="/me", tags=["Profile"])

NO_CONTENT = 204


# Profil de l'appelant (créé s'il n'existe pas encore) ; la connexion passe par PUT /me/sign-in.
@router.get("")
def me(identity: Identity = Depends(current_identity)) -> dict[str, Any]:
    profile = provision(identity)
    return {"id": profile.id, "email": profile.email, "displayName": profile.display_name, "serviceId": profile.service_id}


# Appelée par le serveur du front à chaque connexion : crée le profil ou met à jour son adresse, son nom
# et sa date de dernière connexion, puis enregistre son service Azure AD (« department » de Graph).
@router.put("/sign-in", status_code=NO_CONTENT)
def sign_in(raw: dict[str, Any] = Depends(json_object), identity: Identity = Depends(current_identity)) -> Response:
    profile = provision(identity)
    services.record_department(profile.id, raw)
    return Response(status_code=NO_CONTENT)


@router.get("/preferences")
def preferences(profile: Profile = Depends(current_profile)) -> dict[str, Any]:
    return services.preferences(profile.id).to_json()


# Seules les préférences envoyées changent ; null remet une préférence à vide.
@router.patch("/preferences")
def revise_preferences(
    changes: dict[str, Any] = Depends(json_object), profile: Profile = Depends(current_profile)
) -> dict[str, Any]:
    return services.revise_preferences(profile.id, changes).to_json()


@router.get("/favorites")
def favorites(profile: Profile = Depends(current_profile)) -> dict[str, Any]:
    return services.favorites(profile.id).to_json()


# « :path » : un numéro d'affaire peut contenir « / ».
# PUT et DELETE sont idempotents : ajouter deux fois ou retirer un favori absent répond 204.
@router.put("/favorites/projects/{project_id:path}", status_code=NO_CONTENT)
def add_favorite_project(project_id: str, profile: Profile = Depends(current_profile)) -> Response:
    services.add_favorite_project(profile.id, project_id)
    return Response(status_code=NO_CONTENT)


@router.delete("/favorites/projects/{project_id:path}", status_code=NO_CONTENT)
def remove_favorite_project(project_id: str, profile: Profile = Depends(current_profile)) -> Response:
    services.remove_favorite_project(profile.id, project_id)
    return Response(status_code=NO_CONTENT)


@router.put("/favorites/layers/{layer_id}", status_code=NO_CONTENT)
def add_favorite_layer(layer_id: str, profile: Profile = Depends(current_profile)) -> Response:
    services.add_favorite_layer(profile.id, layer_id)
    return Response(status_code=NO_CONTENT)


@router.delete("/favorites/layers/{layer_id}", status_code=NO_CONTENT)
def remove_favorite_layer(layer_id: str, profile: Profile = Depends(current_profile)) -> Response:
    services.remove_favorite_layer(profile.id, layer_id)
    return Response(status_code=NO_CONTENT)


# 201 si l'adresse est ajoutée, 200 si elle était déjà en favori ; 422 au-delà de 20 adresses.
@router.post("/favorites/addresses")
def add_favorite_address(
    raw: dict[str, Any] = Depends(json_object), profile: Profile = Depends(current_profile)
) -> JSONResponse:
    address, created = services.add_favorite_address(profile.id, raw)
    return JSONResponse(address.to_json(), status_code=201 if created else 200)


@router.delete("/favorites/addresses/{address_id}", status_code=NO_CONTENT)
def remove_favorite_address(address_id: str, profile: Profile = Depends(current_profile)) -> Response:
    services.remove_favorite_address(profile.id, address_id)
    return Response(status_code=NO_CONTENT)


# Reprise unique des favoris gardés dans le navigateur ; renvoie l'état après fusion.
@router.post("/favorites/import")
def import_favorites(
    payload: dict[str, Any] = Depends(json_object), profile: Profile = Depends(current_profile)
) -> dict[str, Any]:
    imported_favorites, imported_preferences = services.import_favorites(profile.id, payload)
    return {"favorites": imported_favorites.to_json(), "preferences": imported_preferences.to_json()}


# Couches ajoutées par l'agent (ADR-0035 du front) : flux WMS, WMTS, XYZ, et fichiers convertis en
# GeoJSON (ADR-0037 du front), dont la liste ne donne que l'emprise.
@router.get("/layers")
def user_layers(profile: Profile = Depends(current_profile)) -> list[dict[str, Any]]:
    return [layer.to_json() for layer in services.user_layers(profile.id)]


@router.post("/layers", status_code=201)
def add_user_layer(raw: dict[str, Any] = Depends(json_object), profile: Profile = Depends(current_profile)) -> dict[str, Any]:
    return services.add_user_layer(profile.id, raw).to_json()


@router.get("/layers/{layer_id}/geojson")
def user_layer_geojson(layer_id: str, profile: Profile = Depends(current_profile)) -> dict[str, Any]:
    return services.user_layer_geojson(profile.id, layer_id)


@router.patch("/layers/{layer_id}")
def revise_user_layer(
    layer_id: str, raw: dict[str, Any] = Depends(json_object), profile: Profile = Depends(current_profile)
) -> dict[str, Any]:
    return services.revise_user_layer(profile.id, layer_id, raw).to_json()


# Retire aussi la couche des favoris et de « Mes couches ».
@router.delete("/layers/{layer_id}", status_code=NO_CONTENT)
def remove_user_layer(layer_id: str, profile: Profile = Depends(current_profile)) -> Response:
    services.remove_user_layer(profile.id, layer_id)
    return Response(status_code=NO_CONTENT)
