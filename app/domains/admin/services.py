# Le métier de l'administration : contrôle des données reçues, garde-fous sur les rôles, mise en forme des
# réponses (clés en camelCase, comme le reste de l'API). Chaque fonction ouvre une transaction.

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import OperationalError

from app.core.errors import InvalidRequest, NotFound, Unprocessable
from app.core.profile import ADMIN_ROLE, USER_ROLE
from app.database.connection import refonte_transaction
from app.domains.admin import editing, queries

def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _number(value: Any) -> float | None:
    return None if value is None else float(value)


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


# --- Catégories de couches ---------------------------------------------------------------------------


# --- Catalogue des couches ---------------------------------------------------------------------------


# --- Référentiels en lecture -------------------------------------------------------------------------


# --- Explorateur de la base (l'édition des lignes est dans editing.py) ----------------------------------------------------------

PAGE_SIZES = (25, 50, 100)
MAX_OFFSET = 1_000_000
CELL_MAX_LENGTH = 300
TABLE_READ_TIMEOUT_MS = 5000
# Code PostgreSQL d'une requête interrompue par statement_timeout.
QUERY_CANCELED = "57014"


def database_tables() -> list[dict[str, Any]]:
    with refonte_transaction() as connection:
        return [
            {
                "name": row["name"],
                "estimatedRows": row["estimated_rows"],
                "sizeBytes": row["size_bytes"],
                "columns": row["columns"],
                **editing.rights(row["name"]),
            }
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
        references = queries.foreign_keys(connection, table)
        try:
            rows = queries.table_rows(connection, table, columns, page_size + 1, start, CELL_MAX_LENGTH, TABLE_READ_TIMEOUT_MS)
        except OperationalError as error:
            if getattr(error.orig, "sqlstate", None) != QUERY_CANCELED:
                raise
            raise Unprocessable(f"Lecture de {table} trop longue à cette position : revenez vers le début de la table.") from None

    return {
        "name": table,
        "estimatedRows": known[table]["estimated_rows"],
        **editing.rights(table),
        "columns": [editing.column_json(column, references.get(column["name"])) for column in columns],
        "rows": [list(row) for row in rows[:page_size]],
        "offset": start,
        "limit": page_size,
        "hasMore": len(rows) > page_size,
    }


# Lignes que propose une colonne qui pointe vers une autre table (clé étrangère) : valeur et libellé, rangées
# par libellé. truncated : la table visée a plus de MAX_CHOICES lignes, le front garde alors un champ texte.
MAX_CHOICES = 1000


def column_choices(table: str, column: str) -> dict[str, Any]:
    with refonte_transaction() as connection:
        known = {row["name"] for row in queries.database_tables(connection)}
        if table not in known:
            raise NotFound(f"Table introuvable : {table}")
        reference = queries.foreign_keys(connection, table).get(column)
        if reference is None:
            raise NotFound(f"La colonne {column} de {table} ne pointe vers aucune table.")
        target_columns = [found["name"] for found in queries.table_columns(connection, reference["table"])]
        label = editing.label_column(target_columns, reference["column"])
        rows = queries.reference_choices(connection, reference["table"], reference["column"], label, MAX_CHOICES + 1)
    return {
        "table": reference["table"],
        "choices": [{"value": value, "label": text} for value, text in rows[:MAX_CHOICES]],
        "truncated": len(rows) > MAX_CHOICES,
    }
