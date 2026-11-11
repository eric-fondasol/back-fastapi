# Le métier de l'administration : contrôle des données reçues, garde-fous sur les rôles, mise en forme des
# réponses (clés en camelCase, comme le reste de l'API). Chaque fonction ouvre une transaction.

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import OperationalError

from app.core.errors import Conflict, InvalidRequest, NotFound, Unprocessable
from app.core.profile import ADMIN_ROLE, USER_ROLE, Profile
from app.database.connection import refonte_transaction
from app.domains.admin import queries

CATEGORY_CODE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
LABEL_MAX_LENGTH = 200
ROLES = (USER_ROLE, ADMIN_ROLE)


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _number(value: Any) -> float | None:
    return None if value is None else float(value)


def _label(payload: dict[str, Any], key: str, required: bool) -> str | None:
    value = payload.get(key)
    if value is None or (isinstance(value, str) and value.strip() == ""):
        if required:
            raise InvalidRequest(f"{key} est obligatoire.")
        return None
    if not isinstance(value, str) or len(value.strip()) > LABEL_MAX_LENGTH:
        raise InvalidRequest(f"{key} doit être un texte de {LABEL_MAX_LENGTH} caractères au plus.")
    return value.strip()


def _user_json(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "displayName": row["display_name"],
        "businessUnitCode": row["business_unit_code"],
        "businessLine": row["business_line"],
        "lastLoginAt": _iso(row["last_login_at"]),
        "roles": list(row["roles"] or []),
    }


# --- Utilisateurs et rôles -------------------------------------------------------------------------


def users() -> list[dict[str, Any]]:
    with refonte_transaction() as connection:
        return [_user_json(row) for row in queries.users(connection)]


# Donne ou retire le rôle admin. Un admin ne peut pas se retirer le sien, ni retirer le dernier admin.
def change_role(caller: Profile, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    role = payload.get("role")
    if role not in ROLES:
        raise InvalidRequest("role attendu : user ou admin.")
    try:
        user_id = str(uuid.UUID(user_id))
    except ValueError:
        raise NotFound(f"Utilisateur introuvable : {user_id}") from None

    with refonte_transaction() as connection:
        admins = queries.locked_admin_ids(connection, ADMIN_ROLE)
        if queries.user(connection, user_id) is None:
            raise NotFound(f"Utilisateur introuvable : {user_id}")

        if role == ADMIN_ROLE:
            queries.grant_role(connection, user_id, USER_ROLE, _now())
            queries.grant_role(connection, user_id, ADMIN_ROLE, _now())
        elif user_id in admins:
            if user_id == caller.id:
                raise Conflict("Vous ne pouvez pas retirer votre propre rôle administrateur.")
            if len(admins) <= 1:
                raise Conflict("Il doit rester au moins un administrateur.")
            queries.revoke_role(connection, user_id, ADMIN_ROLE)

        return _user_json(queries.user(connection, user_id))


# Utilisé par la commande grant_admin : les premiers admins, quand personne ne peut encore les nommer.
def grant_admin_by_email(email: str) -> dict[str, Any]:
    with refonte_transaction() as connection:
        user_id = queries.user_id_by_email(connection, email)
        if user_id is None:
            raise NotFound(f"Aucun profil pour {email} : l'agent doit s'être connecté une fois.")
        queries.grant_role(connection, user_id, USER_ROLE, _now())
        queries.grant_role(connection, user_id, ADMIN_ROLE, _now())
        return _user_json(queries.user(connection, user_id))


# --- Activité ----------------------------------------------------------------------------------------


def activity() -> dict[str, Any]:
    with refonte_transaction() as connection:
        totals = queries.activity_totals(connection)
        weeks = queries.weekly_active_users(connection)
        lines = queries.active_users_by_business_line(connection)
        searches = queries.recent_address_searches(connection)
        days = queries.daily_requests(connection)
        times = queries.response_times(connection)
        actions = queries.top_actions(connection)
        volumes = {row["name"]: row["estimated_rows"] for row in queries.data_volumes(connection)}

    return {
        "periodDays": queries.ACTIVITY_DAYS,
        "activeUsers": totals["active_users"],
        "profiles": totals["profiles"],
        "requests": totals["requests"],
        "serverErrors": totals["server_errors"],
        "addressSearches": totals["address_searches"],
        "weeklyActiveUsers": [{"weekStart": row["week_start"].date().isoformat(), "activeUsers": row["active_users"]} for row in weeks],
        "activeUsersByBusinessLine": [
            {
                "businessLine": row["business_line"],
                "label": {"fr": row["label_fr"], "en": row["label_en"]},
                "activeUsers": row["active_users"],
            }
            for row in lines
        ],
        "dailyRequests": [
            {"day": row["day"].date().isoformat(), "requests": row["requests"], "serverErrors": row["server_errors"]} for row in days
        ],
        "responseTimeMs": {"p50": _number(times["p50"]), "p95": _number(times["p95"])},
        "topActions": [{"action": row["action"], "requests": row["requests"]} for row in actions],
        "dataVolumes": [{"table": table, "estimatedRows": volumes.get(table)} for table in queries.VOLUME_TABLES],
        "recentAddressSearches": [
            {
                "at": _iso(row["horodatage"]),
                "userServiceCode": row["user_service_code"],
                "userServiceName": row["user_service_name"],
                "searchedDepartment": row["research_department_code"],
                "authorized": row["is_authorized"],
            }
            for row in searches
        ],
    }


# --- Business units et métiers -----------------------------------------------------------------------


def business_units() -> list[dict[str, Any]]:
    with refonte_transaction() as connection:
        return [
            {
                "code": row["code"],
                "label": row["libelle"],
                "businessLine": row["business_line"],
                "fullAccess": row["full_access"],
                "users": row["users"],
            }
            for row in queries.business_units(connection)
        ]


def _business_line_json(row: dict[str, Any]) -> dict[str, Any]:
    return {"code": row["code"], "label": {"fr": row["label_fr"], "en": row["label_en"]}, "position": row["position"]}


def business_lines() -> list[dict[str, Any]]:
    with refonte_transaction() as connection:
        return [_business_line_json(row) for row in queries.business_lines(connection)]


def update_business_line(code: str, payload: dict[str, Any]) -> dict[str, Any]:
    label_fr = _label(payload, "labelFr", required=True)
    label_en = _label(payload, "labelEn", required=False)
    with refonte_transaction() as connection:
        if not queries.update_business_line(connection, code, label_fr, label_en):
            raise NotFound(f"Métier introuvable : {code}")
        return next(_business_line_json(row) for row in queries.business_lines(connection) if row["code"] == code)


# --- Catégories de couches ---------------------------------------------------------------------------


def _category_json(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": row["code"],
        "label": {"fr": row["label_fr"], "en": row["label_en"]},
        "position": row["position"],
        "layers": row["layers"],
    }


def layer_categories() -> list[dict[str, Any]]:
    with refonte_transaction() as connection:
        return [_category_json(row) for row in queries.layer_categories(connection)]


def create_layer_category(caller: Profile, payload: dict[str, Any]) -> dict[str, Any]:
    code = payload.get("code")
    if not isinstance(code, str) or not CATEGORY_CODE.match(code):
        raise InvalidRequest("code attendu : minuscules, chiffres et tirets, 64 caractères au plus.")
    label_fr = _label(payload, "labelFr", required=True)
    label_en = _label(payload, "labelEn", required=False)

    with refonte_transaction() as connection:
        if queries.layer_category(connection, code) is not None:
            raise Conflict(f"La catégorie {code} existe déjà.")
        queries.create_layer_category(connection, code, label_fr, label_en, caller.email)
        return _category_json(queries.layer_category(connection, code))


def update_layer_category(caller: Profile, code: str, payload: dict[str, Any]) -> dict[str, Any]:
    label_fr = _label(payload, "labelFr", required=True)
    label_en = _label(payload, "labelEn", required=False)
    with refonte_transaction() as connection:
        if queries.layer_category(connection, code) is None:
            raise NotFound(f"Catégorie introuvable : {code}")
        queries.update_layer_category(connection, code, label_fr, label_en, caller.email)
        return _category_json(queries.layer_category(connection, code))


# Le nouvel ordre doit citer chaque catégorie existante une seule fois.
def reorder_layer_categories(caller: Profile, payload: dict[str, Any]) -> list[dict[str, Any]]:
    codes = payload.get("codes")
    if not isinstance(codes, list) or not all(isinstance(code, str) for code in codes) or len(set(codes)) != len(codes):
        raise InvalidRequest("codes attendu : la liste des codes de catégorie, sans doublon.")
    with refonte_transaction() as connection:
        existing = {row["code"] for row in queries.layer_categories(connection)}
        if set(codes) != existing:
            raise InvalidRequest("codes doit citer toutes les catégories existantes, et elles seules.")
        queries.reorder_layer_categories(connection, codes, caller.email)
        return [_category_json(row) for row in queries.layer_categories(connection)]


def delete_layer_category(code: str) -> None:
    with refonte_transaction() as connection:
        category = queries.layer_category(connection, code)
        if category is None:
            raise NotFound(f"Catégorie introuvable : {code}")
        if category["layers"] > 0:
            raise Conflict(f"La catégorie {code} contient encore {category['layers']} couche(s).")
        queries.delete_layer_category(connection, code)


# --- Catalogue des couches ---------------------------------------------------------------------------


def _catalog_layer_json(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": row["code"],
        "category": row["category"],
        "country": row["country"],
        "label": {"fr": row["label_fr"], "en": row["label_en"]},
        "kind": row["kind"],
        "url": row["url"],
        "attribution": row["attribution"],
        "minZoom": _number(row["min_zoom"]),
        "maxZoom": _number(row["max_zoom"]),
        "enabled": row["enabled"],
    }


def catalog_layers() -> list[dict[str, Any]]:
    with refonte_transaction() as connection:
        return [_catalog_layer_json(row) for row in queries.catalog_layers(connection)]


# Seules la catégorie et l'activation changent ; URL, paramètres et type restent ceux des migrations.
def update_catalog_layer(caller: Profile, code: str, payload: dict[str, Any]) -> dict[str, Any]:
    unknown = set(payload) - {"category", "enabled"}
    if unknown:
        raise InvalidRequest(f"Champs non modifiables : {', '.join(sorted(unknown))}.")
    with refonte_transaction() as connection:
        layer = queries.catalog_layer(connection, code)
        if layer is None:
            raise NotFound(f"Couche introuvable : {code}")

        category = payload.get("category", layer["category"])
        enabled = payload.get("enabled", layer["enabled"])
        if not isinstance(enabled, bool):
            raise InvalidRequest("enabled doit valoir true ou false.")
        if not isinstance(category, str) or queries.layer_category(connection, category) is None:
            raise InvalidRequest(f"Catégorie inconnue : {category}")

        queries.update_catalog_layer(connection, code, category, enabled, caller.email)
        return _catalog_layer_json(queries.catalog_layer(connection, code))


# --- Référentiels en lecture -------------------------------------------------------------------------


def referentials() -> dict[str, Any]:
    with refonte_transaction() as connection:
        return {
            "altimetricReferences": [
                {"code": row["code"], "label": {"fr": row["label_fr"], "en": row["label_en"]}}
                for row in queries.altimetric_references(connection)
            ],
            "noDocsGedReasons": [{"code": str(row["id"]), "label": row["libelle"]} for row in queries.no_docs_ged_reasons(connection)],
            "geolocationReliabilities": [
                {"scope": row["scope"], "level": row["level"], "reliability": row["reliability"], "label": row["libelle"]}
                for row in queries.geolocation_reliabilities(connection)
            ],
        }


# --- Explorateur de la base, en lecture seule ----------------------------------------------------------

PAGE_SIZES = (25, 50, 100)
MAX_OFFSET = 1_000_000
CELL_MAX_LENGTH = 300
TABLE_READ_TIMEOUT_MS = 5000
# Code PostgreSQL d'une requête interrompue par statement_timeout.
QUERY_CANCELED = "57014"


def database_tables() -> list[dict[str, Any]]:
    with refonte_transaction() as connection:
        return [
            {"name": row["name"], "estimatedRows": row["estimated_rows"], "sizeBytes": row["size_bytes"], "columns": row["columns"]}
            for row in queries.database_tables(connection)
        ]


def _page_parameter(value: str | None, default: int, allowed: tuple[int, ...] | None, maximum: int, name: str) -> int:
    if value is None:
        return default
    if not value.isdigit():
        raise InvalidRequest(f"{name} doit être un entier positif.")
    number = int(value)
    if (allowed is not None and number not in allowed) or number > maximum:
        raise InvalidRequest(f"{name} hors limites.")
    return number


# Une page d'une table du schéma public. Le nom doit être celui d'une table existante (404 sinon).
def table_page(table: str, limit: str | None, offset: str | None) -> dict[str, Any]:
    page_size = _page_parameter(limit, PAGE_SIZES[1], PAGE_SIZES, max(PAGE_SIZES), "limit")
    start = _page_parameter(offset, 0, None, MAX_OFFSET, "offset")

    with refonte_transaction() as connection:
        known = {row["name"]: row for row in queries.database_tables(connection)}
        if table not in known:
            raise NotFound(f"Table introuvable : {table}")
        columns = queries.table_columns(connection, table)
        try:
            rows = queries.table_rows(connection, table, columns, page_size + 1, start, CELL_MAX_LENGTH, TABLE_READ_TIMEOUT_MS)
        except OperationalError as error:
            if getattr(error.orig, "sqlstate", None) != QUERY_CANCELED:
                raise
            raise Unprocessable(f"Lecture de {table} trop longue à cette position : revenez vers le début de la table.") from None

    return {
        "name": table,
        "estimatedRows": known[table]["estimated_rows"],
        "columns": [
            {"name": column["name"], "type": column["type"], "nullable": column["nullable"], "primaryKey": column["primary_key"]}
            for column in columns
        ],
        "rows": [list(row) for row in rows[:page_size]],
        "offset": start,
        "limit": page_size,
        "hasMore": len(rows) > page_size,
    }
