# Le SQL de l'édition générique des tables de l'administration (US-ADMIN-09 de docs/features/admin.md du
# front). Noms de table et de colonnes : toujours issus du catalogue PostgreSQL (editing.py refuse tout
# autre nom), entourés de guillemets par identifier(). Les valeurs, reçues en texte, passent en paramètres
# et sont converties par PostgreSQL vers le type de la colonne (CAST), qui refuse une valeur mal formée.

import re
from typing import Any

from sqlalchemy import Connection, text

from app.domains.admin.queries import identifier

GEOMETRY_TYPES = ("geometry", "geography")
DECLARED_SRID = re.compile(r"^geometry\(\w+,(\d+)\)$")


def set_timeout(connection: Connection, timeout_ms: int) -> None:
    connection.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))


# Une géométrie se saisit en WKT ; sans SRID dans le texte, elle reçoit celui que déclare la colonne.
def _typed(column: dict[str, Any], parameter: str) -> str:
    if column["base_type"] in GEOMETRY_TYPES:
        cast = f"CAST(:{parameter} AS {column['base_type']})"
        srid = DECLARED_SRID.match(column["type"])
        return f"ST_SetSRID({cast}, {srid.group(1)})" if srid else cast
    return f"CAST(:{parameter} AS {column['type']})"


def _as_text(column: dict[str, Any]) -> str:
    name = identifier(column["name"])
    return f"ST_AsText({name})" if column["base_type"] in GEOMETRY_TYPES else f"{name}::text"


def _key_filter(key_columns: list[dict[str, Any]], key: dict[str, str], parameters: dict[str, Any]) -> str:
    conditions = []
    for index, column in enumerate(key_columns):
        parameters[f"k{index}"] = key[column["name"]]
        conditions.append(f"{identifier(column['name'])} = {_typed(column, f'k{index}')}")
    return " AND ".join(conditions)


def _returning(key_columns: list[dict[str, Any]]) -> str:
    return ", ".join(f"{_as_text(column)} AS {identifier(column['name'])}" for column in key_columns)


# La ligne entière, chaque valeur en texte et sans coupure (le formulaire de modification la reprend).
def row(connection: Connection, table: str, columns: list[dict[str, Any]], key: dict[str, str]) -> dict[str, Any] | None:
    parameters: dict[str, Any] = {}
    cells = ", ".join(f"{_as_text(column)} AS {identifier(column['name'])}" for column in columns)
    where = _key_filter([column for column in columns if column["primary_key"]], key, parameters)
    found = connection.execute(text(f"SELECT {cells} FROM public.{identifier(table)} WHERE {where}"), parameters).mappings().first()
    return None if found is None else dict(found)


# values : colonne → texte ou None ; managed : colonne → expression SQL (horodatage, auteur).
def insert(
    connection: Connection,
    table: str,
    columns: dict[str, dict[str, Any]],
    values: dict[str, str | None],
    managed: dict[str, str],
    parameters: dict[str, Any],
) -> dict[str, Any]:
    names, expressions = [], []
    for index, (name, value) in enumerate(values.items()):
        parameters[f"v{index}"] = value
        names.append(identifier(name))
        expressions.append(_typed(columns[name], f"v{index}"))
    for name, expression in managed.items():
        names.append(identifier(name))
        expressions.append(expression)
    target = f"public.{identifier(table)}"
    body = f"({', '.join(names)}) VALUES ({', '.join(expressions)})" if names else "DEFAULT VALUES"
    returning = _returning([column for column in columns.values() if column["primary_key"]])
    return dict(connection.execute(text(f"INSERT INTO {target} {body} RETURNING {returning}"), parameters).mappings().one())


def update(
    connection: Connection,
    table: str,
    columns: dict[str, dict[str, Any]],
    key: dict[str, str],
    values: dict[str, str | None],
    managed: dict[str, str],
    parameters: dict[str, Any],
) -> dict[str, Any] | None:
    assignments = []
    for index, (name, value) in enumerate(values.items()):
        parameters[f"v{index}"] = value
        assignments.append(f"{identifier(name)} = {_typed(columns[name], f'v{index}')}")
    assignments += [f"{identifier(name)} = {expression}" for name, expression in managed.items()]
    key_columns = [column for column in columns.values() if column["primary_key"]]
    where = _key_filter(key_columns, key, parameters)
    sql = f"UPDATE public.{identifier(table)} SET {', '.join(assignments)} WHERE {where} RETURNING {_returning(key_columns)}"
    found = connection.execute(text(sql), parameters).mappings().first()
    return None if found is None else dict(found)


def delete(connection: Connection, table: str, columns: list[dict[str, Any]], key: dict[str, str]) -> int:
    parameters: dict[str, Any] = {}
    where = _key_filter([column for column in columns if column["primary_key"]], key, parameters)
    return connection.execute(text(f"DELETE FROM public.{identifier(table)} WHERE {where}"), parameters).rowcount


# Les clés étrangères qui pointent vers la table, avec leur règle de suppression (confdeltype :
# c = cascade, r et a = refus, n et d = mise à NULL ou à la valeur par défaut).
def referencing_keys(connection: Connection, table: str) -> list[dict[str, Any]]:
    return [
        dict(found)
        for found in connection.execute(
            text(
                """
                SELECT child.relname AS child, c.confdeltype::text AS on_delete,
                       ARRAY(SELECT a.attname::text FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, position)
                             JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum ORDER BY k.position) AS child_columns,
                       ARRAY(SELECT a.attname::text FROM unnest(c.confkey) WITH ORDINALITY AS k(attnum, position)
                             JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.attnum ORDER BY k.position) AS parent_columns
                FROM pg_constraint c
                JOIN pg_class child ON child.oid = c.conrelid
                JOIN pg_class parent ON parent.oid = c.confrelid
                JOIN pg_namespace n ON n.oid = parent.relnamespace
                WHERE c.contype = 'f' AND n.nspname = 'public' AND parent.relname = :table
                ORDER BY child.relname, c.conname
                """
            ),
            {"table": table},
        ).mappings()
    ]


def key_filter(columns: list[dict[str, Any]], key: dict[str, str], parameters: dict[str, Any]) -> str:
    return _key_filter([column for column in columns if column["primary_key"]], key, parameters)


# Les lignes de child qui pointent vers les lignes de parent retenues par parent_filter.
def referencing_filter(reference: dict[str, Any], parent: str, parent_filter: str) -> str:
    child_columns = ", ".join(identifier(name) for name in reference["child_columns"])
    parent_columns = ", ".join(identifier(name) for name in reference["parent_columns"])
    return f"({child_columns}) IN (SELECT {parent_columns} FROM public.{identifier(parent)} WHERE {parent_filter})"


def count(connection: Connection, table: str, where: str, parameters: dict[str, Any]) -> int:
    return connection.execute(text(f"SELECT count(*) FROM public.{identifier(table)} WHERE {where}"), parameters).scalar_one()
