# Édition générique des tables de l'administration (US-ADMIN-09 de docs/features/admin.md du front) :
# création, modification et suppression de lignes, limitées à une liste fermée de tables. Les colonnes et
# la clé primaire viennent du catalogue PostgreSQL ; les valeurs, reçues en texte, sont converties par
# PostgreSQL, dont les refus (type, contrainte, clé étrangère) deviennent des réponses 409 ou 422 lisibles.

import json
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.exc import DataError, IntegrityError, InternalError, OperationalError

from app.core.errors import Conflict, InvalidRequest, NotFound, Unprocessable
from app.core.profile import ADMIN_ROLE, Profile
from app.database.connection import refonte_transaction
from app.domains.admin import editing_queries, queries

# Table → suppression permise. users et projects : modification seulement (décision du 12/11/2026).
# parametrages n'a pas de clé primaire : lecture seule.
EDITABLE_TABLES: dict[str, bool] = {
    "business_lines": True,
    "business_units": True,
    "catalog_layers": True,
    "departments": True,
    "fuseau_work_versions": True,
    "fuseau_works": True,
    "geolocation_reliabilities": True,
    "gw_reference_levels": True,
    "layer_categories": True,
    "no_docs_ged_reasons": True,
    "no_geo_project_reasons": True,
    "no_geo_survey_reasons": True,
    "penetrometer_machine_types": True,
    "penetrometer_readings": True,
    "penetrometer_tests": True,
    "project_business_lines": True,
    "project_types": True,
    "projects": False,
    "referentiels": True,
    "roles": True,
    "saved_page_version_files": True,
    "saved_page_versions": True,
    "saved_pages": True,
    "standards": True,
    "user_roles": True,
    "users": False,
    "waiting_images": True,
}

# Colonnes tenues par le serveur, jamais saisies : horodatages et auteur de la dernière modification.
MANAGED_COLUMNS = ("created_at", "updated_at", "updated_by")
KEY_MAX_LENGTH = 2000
WRITE_TIMEOUT_MS = 5000
IMPACT_DEPTH = 4

UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"
QUERY_CANCELED = "57014"
# Classes SQLSTATE d'une valeur refusée : 22 (donnée mal formée, hors limites), 23 (contrainte),
# XX000 (erreur interne levée par PostGIS sur un WKT illisible).
REFUSED_VALUE_CLASSES = ("22", "23")
POSTGIS_PARSE_ERROR = "XX000"


def rights(table: str) -> dict[str, bool]:
    return {"editable": table in EDITABLE_TABLES, "deletable": EDITABLE_TABLES.get(table, False)}


# Une clé primaire qui a une valeur par défaut (gen_random_uuid(), séquence) est générée par la base, jamais
# saisie ; une clé naturelle sans valeur par défaut (code d'un métier, user_id et role_code) se saisit.
def is_writable(column: dict[str, Any]) -> bool:
    generated_key = column["primary_key"] and column["has_default"]
    return not column["identity"] and not column["generated"] and not generated_key and column["name"] not in MANAGED_COLUMNS


# reference : la table visée quand la colonne est une clé étrangère (le front propose alors ses lignes).
def column_json(column: dict[str, Any], reference: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "name": column["name"],
        "type": column["type"],
        "nullable": column["nullable"],
        "primaryKey": column["primary_key"],
        "writable": is_writable(column),
        "hasDefault": column["has_default"] or column["identity"],
        "reference": None if reference is None else reference["table"],
    }


# Colonnes qui nomment une ligne, par préférence : libellé, nom, numéro d'affaire, adresse, code.
LABEL_COLUMNS = ("label_fr", "libelle", "label", "display_name", "name", "project_number", "email", "code", "reference", "type")


def label_column(columns: list[str], key_column: str) -> str:
    return next((name for name in LABEL_COLUMNS if name in columns), key_column)


def _sqlstate(error: Exception) -> str | None:
    return getattr(getattr(error, "orig", None), "sqlstate", None)


def _database_message(error: Exception) -> str:
    diagnostic = getattr(getattr(error, "orig", None), "diag", None)
    primary = getattr(diagnostic, "message_primary", None) or str(getattr(error, "orig", error)).splitlines()[0]
    detail = getattr(diagnostic, "message_detail", None)
    return f"{primary} ({detail})" if detail else primary


# À placer autour de la transaction, pour que l'annulation ait eu lieu quand la réponse part.
@contextmanager
def _database_refusals(table: str) -> Iterator[None]:
    try:
        yield
    except (DataError, IntegrityError, InternalError, OperationalError) as error:
        state = _sqlstate(error) or ""
        if state == UNIQUE_VIOLATION:
            raise Conflict(f"Une ligne de {table} a déjà cette valeur : {_database_message(error)}") from None
        if state == FOREIGN_KEY_VIOLATION:
            raise Conflict(f"Lien vers une autre table refusé : {_database_message(error)}") from None
        if state == QUERY_CANCELED:
            raise Unprocessable(f"L'écriture dans {table} a dépassé {WRITE_TIMEOUT_MS // 1000} s.") from None
        if state[:2] in REFUSED_VALUE_CLASSES or state == POSTGIS_PARSE_ERROR:
            raise Unprocessable(f"Valeur refusée par la base : {_database_message(error)}") from None
        raise


def _columns(connection: Any, table: str) -> list[dict[str, Any]]:
    columns = queries.table_columns(connection, table)
    if not columns:
        raise NotFound(f"Table introuvable : {table}")
    if table not in EDITABLE_TABLES:
        raise Unprocessable(f"La table {table} est en lecture seule.")
    if not any(column["primary_key"] for column in columns):
        raise Unprocessable(f"La table {table} n'a pas de clé primaire : ses lignes ne peuvent pas être désignées.")
    return columns


def _key(raw: Any, columns: list[dict[str, Any]]) -> dict[str, str]:
    if isinstance(raw, str):
        if len(raw) > KEY_MAX_LENGTH:
            raise InvalidRequest("key trop longue.")
        try:
            raw = json.loads(raw)
        except ValueError:
            raise InvalidRequest("key doit être un objet JSON.") from None
    names = {column["name"] for column in columns if column["primary_key"]}
    if not isinstance(raw, dict) or set(raw) != names or not all(isinstance(value, str) for value in raw.values()):
        raise InvalidRequest(f"key attendue : {{{', '.join(sorted(names))}}}, chaque valeur en texte.")
    return raw


def _values(raw: Any, columns: list[dict[str, Any]], creating: bool) -> dict[str, str | None]:
    if not isinstance(raw, dict):
        raise InvalidRequest("values attendu : un objet colonne → valeur.")
    by_name = {column["name"]: column for column in columns}
    for name, value in raw.items():
        column = by_name.get(name)
        if column is None:
            raise InvalidRequest(f"Colonne inconnue : {name}")
        if not is_writable(column) or (column["primary_key"] and not creating):
            raise InvalidRequest(f"La colonne {name} n'est pas modifiable.")
        if value is not None and not isinstance(value, str):
            raise InvalidRequest(f"{name} : la valeur doit être un texte ou null.")
        if value is None and not column["nullable"]:
            raise InvalidRequest(f"{name} est obligatoire.")
    return raw


def _managed(columns: list[dict[str, Any]], caller: Profile, creating: bool, parameters: dict[str, Any]) -> dict[str, str]:
    by_name = {column["name"]: column for column in columns}
    managed: dict[str, str] = {}
    if "updated_by" in by_name:
        parameters["managed_by"] = caller.email
        managed["updated_by"] = ":managed_by"
    if "updated_at" in by_name and not (creating and by_name["updated_at"]["has_default"]):
        managed["updated_at"] = "now()"
    if creating and "created_at" in by_name and not by_name["created_at"]["has_default"]:
        managed["created_at"] = "now()"
    return managed


def row(table: str, key: str | None) -> dict[str, Any]:
    with refonte_transaction() as connection:
        columns = _columns(connection, table)
        found = editing_queries.row(connection, table, columns, _key(key, columns))
    if found is None:
        raise NotFound(f"Ligne introuvable dans {table}.")
    return {"values": found}


def create_row(caller: Profile, table: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _database_refusals(table), refonte_transaction() as connection:
        editing_queries.set_timeout(connection, WRITE_TIMEOUT_MS)
        columns = _columns(connection, table)
        values = _values(payload.get("values", {}), columns, creating=True)
        parameters: dict[str, Any] = {}
        managed = _managed(columns, caller, True, parameters)
        key = editing_queries.insert(connection, table, {column["name"]: column for column in columns}, values, managed, parameters)
    return {"key": key}


def update_row(caller: Profile, table: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _database_refusals(table), refonte_transaction() as connection:
        editing_queries.set_timeout(connection, WRITE_TIMEOUT_MS)
        columns = _columns(connection, table)
        key = _key(payload.get("key"), columns)
        values = _values(payload.get("values", {}), columns, creating=False)
        parameters: dict[str, Any] = {}
        managed = _managed(columns, caller, False, parameters)
        if not values and not managed:
            raise InvalidRequest("Aucune valeur à modifier.")
        updated = editing_queries.update(connection, table, {column["name"]: column for column in columns}, key, values, managed, parameters)
    if updated is None:
        raise NotFound(f"Ligne introuvable dans {table}.")
    return {"key": updated}


def _deletable_columns(connection: Any, table: str) -> list[dict[str, Any]]:
    columns = _columns(connection, table)
    if not EDITABLE_TABLES[table]:
        raise Unprocessable(f"La suppression n'est pas permise dans {table}.")
    return columns


# Ce que la suppression entraînerait, en suivant les clés étrangères : lignes supprimées en cascade (sur
# IMPACT_DEPTH niveaux), lignes qui l'empêchent, lignes qui perdraient leur lien (mise à NULL).
def _impact(connection: Any, table: str, where: str, parameters: dict[str, Any], path: frozenset[str], depth: int, found: dict[str, dict[str, int]]) -> None:
    for reference in editing_queries.referencing_keys(connection, table):
        child = reference["child"]
        child_filter = editing_queries.referencing_filter(reference, table, where)
        rows = editing_queries.count(connection, child, child_filter, parameters)
        if rows == 0:
            continue
        kind = {"c": "cascades", "r": "blockers", "a": "blockers"}.get(reference["on_delete"], "detached")
        found[kind][child] += rows
        if kind == "cascades" and child not in path and depth < IMPACT_DEPTH:
            _impact(connection, child, child_filter, parameters, path | {child}, depth + 1, found)


def deletion_impact(table: str, key: str | None) -> dict[str, Any]:
    with _database_refusals(table), refonte_transaction() as connection:
        editing_queries.set_timeout(connection, WRITE_TIMEOUT_MS)
        columns = _deletable_columns(connection, table)
        parameters: dict[str, Any] = {}
        where = editing_queries.key_filter(columns, _key(key, columns), parameters)
        if editing_queries.count(connection, table, where, parameters) == 0:
            raise NotFound(f"Ligne introuvable dans {table}.")
        found: dict[str, dict[str, int]] = {"cascades": defaultdict(int), "blockers": defaultdict(int), "detached": defaultdict(int)}
        _impact(connection, table, where, parameters, frozenset({table}), 1, found)
    return {kind: [{"table": name, "rows": rows} for name, rows in sorted(tables.items())] for kind, tables in found.items()}


# Retirer un rôle admin (ligne de user_roles) : jamais le sien, jamais le dernier. Les autres colonnes de
# user_roles forment la clé primaire, que la modification ne touche pas : seule la suppression est à garder.
def _guard_admin_role(connection: Any, caller: Profile, table: str, key: dict[str, str]) -> None:
    if table != "user_roles" or key.get("role_code") != ADMIN_ROLE:
        return
    admins = queries.locked_admin_ids(connection, ADMIN_ROLE)
    if key.get("user_id") not in admins:
        return
    if key["user_id"] == caller.id:
        raise Conflict("Vous ne pouvez pas retirer votre propre rôle administrateur.")
    if len(admins) <= 1:
        raise Conflict("Il doit rester au moins un administrateur.")


def delete_row(caller: Profile, table: str, key: str | None) -> None:
    with _database_refusals(table), refonte_transaction() as connection:
        editing_queries.set_timeout(connection, WRITE_TIMEOUT_MS)
        columns = _deletable_columns(connection, table)
        row_key = _key(key, columns)
        _guard_admin_role(connection, caller, table, row_key)
        if editing_queries.delete(connection, table, columns, row_key) == 0:
            raise NotFound(f"Ligne introuvable dans {table}.")
