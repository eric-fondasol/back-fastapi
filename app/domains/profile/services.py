# Le métier du profil : préférences, favoris (affaires, couches, adresses) et reprise unique des
# favoris que le front gardait dans le navigateur. Repris des handlers du back Symfony.
# Chaque fonction ouvre une transaction : tout ce qu'elle écrit est validé ensemble, ou rien.

import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.errors import InvalidRequest, NotFound, Unprocessable
from app.database.connection import refonte_transaction
from app.domains.profile import queries
from app.domains.profile.entities import (
    FAVORITE_ADDRESS_LIMIT,
    USER_LAYER_LIMIT,
    USER_LAYER_PREFIX,
    FavoriteAddress,
    Favorites,
    Preferences,
    UserLayer,
    department,
    layer_id,
    layer_name,
    layer_style,
)


# Les dates sont stockées à la seconde (timestamp(0)) : on arrondit avant, pour renvoyer ce qui est stocké.
def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def preferences(user_id: str) -> Preferences:
    with refonte_transaction() as connection:
        return queries.preferences_of(connection, user_id)


def revise_preferences(user_id: str, changes: dict[str, Any]) -> Preferences:
    with refonte_transaction() as connection:
        revised = queries.preferences_of(connection, user_id).revised_with(changes)
        queries.save_preferences(connection, user_id, revised, _now())
        return revised


def favorites(user_id: str) -> Favorites:
    with refonte_transaction() as connection:
        return _favorites(connection, user_id)


def add_favorite_project(user_id: str, project_id: str) -> None:
    with refonte_transaction() as connection:
        if not queries.project_exists(connection, project_id):
            raise NotFound(f"Affaire introuvable : {project_id}")

        queries.add_favorite_project(connection, user_id, project_id, _now())


def remove_favorite_project(user_id: str, project_id: str) -> None:
    with refonte_transaction() as connection:
        queries.remove_favorite_project(connection, user_id, project_id)


def add_favorite_layer(user_id: str, raw_layer_id: str) -> None:
    checked = layer_id(raw_layer_id)

    with refonte_transaction() as connection:
        queries.add_favorite_layer(connection, user_id, checked, _now())


def remove_favorite_layer(user_id: str, raw_layer_id: str) -> None:
    with refonte_transaction() as connection:
        queries.remove_favorite_layer(connection, user_id, raw_layer_id)


# Renvoie l'adresse et True si elle vient d'être créée ; une adresse déjà en favori (même
# identifiant de géocodeur) est renvoyée telle quelle, avec False.
def add_favorite_address(user_id: str, raw: dict[str, Any]) -> tuple[FavoriteAddress, bool]:
    address = FavoriteAddress.of(str(uuid.uuid4()), raw, _now())

    with refonte_transaction() as connection:
        existing = queries.favorite_address_by_external_id(connection, user_id, address.external_id)

        if existing is not None:
            return existing, False

        if queries.favorite_address_count(connection, user_id) >= FAVORITE_ADDRESS_LIMIT:
            raise Unprocessable(f"{FAVORITE_ADDRESS_LIMIT} adresses favorites au plus.")

        queries.add_favorite_address(connection, user_id, address)
        return address, True


def remove_favorite_address(user_id: str, address_id: str) -> None:
    removed = False

    if _is_uuid(address_id):
        with refonte_transaction() as connection:
            removed = queries.remove_favorite_address(connection, user_id, address_id)

    if not removed:
        raise NotFound(f"Adresse favorite introuvable : {address_id}")


# Reprise unique du localStorage du front : fusionne sans doublon ni écrasement.
# - adresses : ajoutées si absentes, dans la limite de 20 ;
# - couches favorites : ajoutées si absentes ;
# - « Mes couches » (mapLayers) : reprises seulement si l'agent n'en a encore aucune en base.
# Tout est contrôlé avant la première écriture : un import invalide n'enregistre rien.
def import_favorites(user_id: str, payload: dict[str, Any]) -> tuple[Favorites, Preferences]:
    now = _now()
    candidates = [FavoriteAddress.of(str(uuid.uuid4()), _address_object(raw), now) for raw in _list(payload, "addresses")]
    layer_ids = list(dict.fromkeys(layer_id(raw) for raw in _list(payload, "layers")))

    with refonte_transaction() as connection:
        current = queries.preferences_of(connection, user_id)
        imported = (
            current.revised_with({"mapLayers": payload["mapLayers"]})
            if "mapLayers" in payload and not current.map_layers
            else None
        )
        room = FAVORITE_ADDRESS_LIMIT - queries.favorite_address_count(connection, user_id)

        for address in candidates:
            if room <= 0:
                break

            if queries.favorite_address_by_external_id(connection, user_id, address.external_id) is not None:
                continue

            queries.add_favorite_address(connection, user_id, address)
            room -= 1

        for checked in layer_ids:
            queries.add_favorite_layer(connection, user_id, checked, now)

        if imported is not None:
            queries.save_preferences(connection, user_id, imported, now)

        return _favorites(connection, user_id), queries.preferences_of(connection, user_id)


def user_layers(user_id: str) -> list[UserLayer]:
    with refonte_transaction() as connection:
        return queries.user_layers(connection, user_id)


# 422 au-delà de USER_LAYER_LIMIT couches par agent.
def add_user_layer(user_id: str, raw: dict[str, Any]) -> UserLayer:
    layer = UserLayer.of(str(uuid.uuid4()), raw, _now())

    with refonte_transaction() as connection:
        if queries.user_layer_count(connection, user_id) >= USER_LAYER_LIMIT:
            raise Unprocessable(f"{USER_LAYER_LIMIT} couches au plus.")

        queries.add_user_layer(connection, user_id, layer)
        return layer


# Nom et style, chacun facultatif mais au moins un. 404 pour une couche absente ou appartenant à un autre agent.
def revise_user_layer(user_id: str, layer_uuid: str, raw: dict[str, Any]) -> UserLayer:
    if "name" not in raw and "style" not in raw:
        raise InvalidRequest("name ou style est requis.")

    name = layer_name(raw.get("name")) if "name" in raw else None
    style = layer_style(raw.get("style")) if "style" in raw else None
    revised = None

    if _is_uuid(layer_uuid):
        with refonte_transaction() as connection:
            revised = queries.revise_user_layer(connection, user_id, layer_uuid, name, style, _now())

    if revised is None:
        raise NotFound(f"Couche introuvable : {layer_uuid}")

    return revised


# 404 pour une couche absente, qui n'est pas un fichier, ou appartenant à un autre agent.
def user_layer_geojson(user_id: str, layer_uuid: str) -> dict[str, Any]:
    geojson = None

    if _is_uuid(layer_uuid):
        with refonte_transaction() as connection:
            geojson = queries.user_layer_geojson(connection, user_id, layer_uuid)

    if geojson is None:
        raise NotFound(f"Couche introuvable : {layer_uuid}")

    return geojson


def remove_user_layer(user_id: str, layer_uuid: str) -> None:
    removed = False

    if _is_uuid(layer_uuid):
        with refonte_transaction() as connection:
            removed = queries.remove_user_layer(connection, user_id, layer_uuid, USER_LAYER_PREFIX + layer_uuid)

    if not removed:
        raise NotFound(f"Couche introuvable : {layer_uuid}")


def _favorites(connection, user_id: str) -> Favorites:
    return Favorites(
        queries.favorite_project_ids(connection, user_id),
        queries.favorite_layer_ids(connection, user_id),
        queries.favorite_addresses(connection, user_id),
    )


# Un champ absent ou null vaut une liste vide ; « {} » aussi, comme en PHP.
def _list(payload: dict[str, Any], name: str) -> list[Any]:
    value = payload.get(name)

    if value is None or value == {}:
        return []

    if not isinstance(value, list):
        raise InvalidRequest(f"{name} doit etre une liste.")

    return value


def _address_object(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise InvalidRequest("Une adresse doit etre un objet.")

    return raw


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False

    return True


# Remplace le département enregistré par celui qu'Azure AD donne aujourd'hui (null l'efface),
# et la business unit qui en découle.
# Sans « department » (Graph n'a pas répondu au front), le département connu est gardé.
def record_department(user_id: str, raw: dict[str, Any]) -> None:
    if "department" not in raw:
        return

    checked = department(raw["department"])

    with refonte_transaction() as connection:
        queries.set_department(connection, user_id, checked)
