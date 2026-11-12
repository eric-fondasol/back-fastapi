# Le SQL de l'administration (ADR-0060 et docs/features/admin.md du front). Chaque fonction reçoit la
# connexion de la transaction ouverte par services.py.

from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

ACTIVITY_DAYS = 30
ACTIVITY_WEEKS = 8
RECENT_SEARCHES = 10


def _rows(connection: Connection, sql: str, **parameters: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(text(sql), parameters).mappings()]


# --- Utilisateurs et rôles -------------------------------------------------------------------------

USER_SELECT = """
    SELECT users.id, users.email, users.display_name, users.business_unit_code, business_units.business_line,
           users.last_login_at,
           ARRAY(SELECT role_code FROM user_roles WHERE user_roles.user_id = users.id ORDER BY role_code) AS roles
    FROM users LEFT JOIN business_units ON business_units.code = users.business_unit_code
"""


def users(connection: Connection) -> list[dict[str, Any]]:
    return _rows(connection, f"{USER_SELECT} ORDER BY users.display_name NULLS LAST, users.email")


def user(connection: Connection, user_id: str) -> dict[str, Any] | None:
    rows = _rows(connection, f"{USER_SELECT} WHERE users.id = :id", id=user_id)
    return rows[0] if rows else None


# Verrouille les lignes admin : deux retraits simultanés ne peuvent pas laisser l'application sans admin.
def locked_admin_ids(connection: Connection, role: str) -> list[str]:
    rows = connection.execute(
        text("SELECT user_id FROM user_roles WHERE role_code = :role FOR UPDATE"), {"role": role}
    ).scalars()
    return [str(user_id) for user_id in rows]


def grant_role(connection: Connection, user_id: str, role: str, at: datetime) -> None:
    connection.execute(
        text("INSERT INTO user_roles (user_id, role_code, granted_at) VALUES (:id, :role, :at) ON CONFLICT DO NOTHING"),
        {"id": user_id, "role": role, "at": at},
    )


def revoke_role(connection: Connection, user_id: str, role: str) -> None:
    connection.execute(text("DELETE FROM user_roles WHERE user_id = :id AND role_code = :role"), {"id": user_id, "role": role})


def user_id_by_email(connection: Connection, email: str) -> str | None:
    value = connection.execute(text("SELECT id FROM users WHERE lower(email) = lower(:email)"), {"email": email}).scalar()
    return None if value is None else str(value)


# --- Activité ----------------------------------------------------------------------------------------


def activity_totals(connection: Connection) -> dict[str, Any]:
    return _rows(
        connection,
        """
        SELECT
            (SELECT count(DISTINCT lower(username)) FROM usage_logs
              WHERE created_at >= now() - make_interval(days => :days) AND username IS NOT NULL) AS active_users,
            (SELECT count(*) FROM usage_logs WHERE created_at >= now() - make_interval(days => :days)) AS requests,
            (SELECT count(*) FROM usage_logs
              WHERE created_at >= now() - make_interval(days => :days) AND status_code >= 500) AS server_errors,
            (SELECT count(*) FROM address_search_tracings
              WHERE horodatage >= now() - make_interval(days => :days)) AS address_searches,
            (SELECT count(*) FROM users) AS profiles
        """,
        days=ACTIVITY_DAYS,
    )[0]


def weekly_active_users(connection: Connection) -> list[dict[str, Any]]:
    return _rows(
        connection,
        """
        SELECT weeks.start AS week_start, count(DISTINCT lower(logs.username)) AS active_users
        FROM generate_series(date_trunc('week', now()) - make_interval(weeks => :weeks - 1), date_trunc('week', now()),
                             interval '1 week') AS weeks(start)
        LEFT JOIN usage_logs logs
               ON logs.created_at >= weeks.start AND logs.created_at < weeks.start + interval '1 week'
              AND logs.username IS NOT NULL
        GROUP BY weeks.start
        ORDER BY weeks.start
        """,
        weeks=ACTIVITY_WEEKS,
    )


# Agents actifs par métier, d'après leur profil (adresse du journal = adresse du profil).
def active_users_by_business_line(connection: Connection) -> list[dict[str, Any]]:
    return _rows(
        connection,
        """
        SELECT business_units.business_line, business_lines.label_fr, business_lines.label_en,
               count(DISTINCT lower(logs.username)) AS active_users
        FROM usage_logs logs
        LEFT JOIN users ON lower(users.email) = lower(logs.username)
        LEFT JOIN business_units ON business_units.code = users.business_unit_code
        LEFT JOIN business_lines ON business_lines.code = business_units.business_line
        WHERE logs.created_at >= now() - make_interval(days => :days) AND logs.username IS NOT NULL
        GROUP BY business_units.business_line, business_lines.label_fr, business_lines.label_en
        ORDER BY active_users DESC, business_units.business_line NULLS LAST
        """,
        days=ACTIVITY_DAYS,
    )


def recent_address_searches(connection: Connection) -> list[dict[str, Any]]:
    return _rows(
        connection,
        """
        SELECT horodatage, user_service_code, user_service_name, research_department_code, is_authorized
        FROM address_search_tracings
        ORDER BY horodatage DESC
        LIMIT :limit
        """,
        limit=RECENT_SEARCHES,
    )


# --- Business units et métiers -----------------------------------------------------------------------


def business_units(connection: Connection) -> list[dict[str, Any]]:
    return _rows(
        connection,
        """
        SELECT business_units.code, business_units.libelle, business_units.business_line, business_units.full_access,
               count(users.id) AS users
        FROM business_units LEFT JOIN users ON users.business_unit_code = business_units.code
        GROUP BY business_units.code
        ORDER BY business_units.code
        """,
    )


def business_lines(connection: Connection) -> list[dict[str, Any]]:
    return _rows(connection, "SELECT code, label_fr, label_en, position FROM business_lines ORDER BY position, code")


def update_business_line(connection: Connection, code: str, label_fr: str, label_en: str | None) -> bool:
    result = connection.execute(
        text("UPDATE business_lines SET label_fr = :fr, label_en = :en WHERE code = :code"),
        {"code": code, "fr": label_fr, "en": label_en},
    )
    return result.rowcount == 1


# --- Catégories et catalogue des couches -------------------------------------------------------------


def layer_categories(connection: Connection) -> list[dict[str, Any]]:
    return _rows(
        connection,
        """
        SELECT categories.code, categories.label_fr, categories.label_en, categories.position, count(layers.id) AS layers
        FROM layer_categories categories LEFT JOIN catalog_layers layers ON layers.category_id = categories.id
        GROUP BY categories.id
        ORDER BY categories.position, categories.code
        """,
    )


def layer_category(connection: Connection, code: str) -> dict[str, Any] | None:
    rows = [row for row in layer_categories(connection) if row["code"] == code]
    return rows[0] if rows else None


def create_layer_category(connection: Connection, code: str, label_fr: str, label_en: str | None, by: str) -> None:
    connection.execute(
        text(
            """
            INSERT INTO layer_categories (code, label_fr, label_en, position, updated_by)
            VALUES (:code, :fr, :en, (SELECT coalesce(max(position), 0) + 1 FROM layer_categories), :by)
            """
        ),
        {"code": code, "fr": label_fr, "en": label_en, "by": by},
    )


def update_layer_category(connection: Connection, code: str, label_fr: str, label_en: str | None, by: str) -> None:
    connection.execute(
        text("UPDATE layer_categories SET label_fr = :fr, label_en = :en, updated_at = now(), updated_by = :by WHERE code = :code"),
        {"code": code, "fr": label_fr, "en": label_en, "by": by},
    )


def reorder_layer_categories(connection: Connection, codes: list[str], by: str) -> None:
    for position, code in enumerate(codes, start=1):
        connection.execute(
            text("UPDATE layer_categories SET position = :position, updated_at = now(), updated_by = :by WHERE code = :code"),
            {"code": code, "position": position, "by": by},
        )


def delete_layer_category(connection: Connection, code: str) -> None:
    connection.execute(text("DELETE FROM layer_categories WHERE code = :code"), {"code": code})


CATALOG_LAYER_SELECT = """
    SELECT layers.code, categories.code AS category, layers.country, layers.label_fr, layers.label_en, layers.kind,
           layers.url, layers.attribution, layers.min_zoom, layers.max_zoom, layers.enabled
    FROM catalog_layers layers JOIN layer_categories categories ON categories.id = layers.category_id
"""


def catalog_layers(connection: Connection) -> list[dict[str, Any]]:
    return _rows(connection, f"{CATALOG_LAYER_SELECT} ORDER BY categories.position, categories.code, layers.position, layers.code")


def catalog_layer(connection: Connection, code: str) -> dict[str, Any] | None:
    rows = _rows(connection, f"{CATALOG_LAYER_SELECT} WHERE layers.code = :code", code=code)
    return rows[0] if rows else None


def update_catalog_layer(connection: Connection, code: str, category: str, enabled: bool, by: str) -> None:
    connection.execute(
        text(
            """
            UPDATE catalog_layers
            SET category_id = (SELECT id FROM layer_categories WHERE code = :category),
                enabled = :enabled, updated_at = now(), updated_by = :by
            WHERE code = :code
            """
        ),
        {"code": code, "category": category, "enabled": enabled, "by": by},
    )


# --- Référentiels en lecture -------------------------------------------------------------------------


def altimetric_references(connection: Connection) -> list[dict[str, Any]]:
    return _rows(connection, "SELECT code, label_fr, label_en FROM referentiels ORDER BY position, code")


def no_docs_ged_reasons(connection: Connection) -> list[dict[str, Any]]:
    return _rows(connection, "SELECT id, libelle FROM no_docs_ged_reasons ORDER BY id")


def geolocation_reliabilities(connection: Connection) -> list[dict[str, Any]]:
    return _rows(connection, "SELECT scope, level, reliability, libelle FROM geolocation_reliabilities ORDER BY scope, level")


# --- Explorateur de la base, en lecture seule ----------------------------------------------------------

# Tables du schéma public, avec leur nombre de lignes estimé par PostgreSQL (reltuples, -1 avant le premier
# ANALYZE) : un count(*) sur les 3 millions de lithologies prendrait plusieurs secondes.
def database_tables(connection: Connection) -> list[dict[str, Any]]:
    return _rows(
        connection,
        """
        SELECT c.relname AS name,
               CASE WHEN c.reltuples < 0 THEN NULL ELSE c.reltuples::bigint END AS estimated_rows,
               pg_total_relation_size(c.oid) AS size_bytes,
               (SELECT count(*) FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped) AS columns
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
        ORDER BY c.relname
        """,
    )


def table_columns(connection: Connection, table: str) -> list[dict[str, Any]]:
    return _rows(
        connection,
        """
        SELECT a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type, t.typname AS base_type,
               NOT a.attnotnull AS nullable,
               EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.oid AND i.indisprimary AND a.attnum = ANY (i.indkey)) AS primary_key,
               a.atthasdef AS has_default, a.attidentity <> '' AS identity, a.attgenerated <> '' AS generated
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
        JOIN pg_type t ON t.oid = a.atttypid
        WHERE n.nspname = 'public' AND c.relname = :table
        ORDER BY a.attnum
        """,
        table=table,
    )


def identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# Chaque valeur est rendue en texte (géométries en WKT), coupée à max_length caractères.
def _cell(column: dict[str, Any], max_length: int) -> str:
    value = identifier(column["name"])
    as_text = f"ST_AsText({value})" if column["base_type"] in ("geometry", "geography") else f"{value}::text"
    return f"CASE WHEN length({as_text}) > {max_length} THEN left({as_text}, {max_length}) || '…' ELSE {as_text} END"


# Une page de la table, rangée par clé primaire quand elle existe. Le nom de table et les colonnes viennent
# du catalogue (services.py refuse tout autre nom), jamais de la requête. statement_timeout borne la lecture.
def table_rows(
    connection: Connection, table: str, columns: list[dict[str, Any]], limit: int, offset: int, max_length: int, timeout_ms: int
) -> list[tuple[Any, ...]]:
    connection.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
    keys = [identifier(column["name"]) for column in columns if column["primary_key"]]
    order = f" ORDER BY {', '.join(keys)}" if keys else ""
    cells = ", ".join(_cell(column, max_length) for column in columns)
    sql = f"SELECT {cells} FROM public.{identifier(table)}{order} LIMIT :limit OFFSET :offset"
    return [tuple(row) for row in connection.execute(text(sql), {"limit": limit, "offset": offset})]


# --- Tableau de bord : séries et volumes ---------------------------------------------------------------

TOP_ACTIONS = 6
VOLUME_TABLES = ("projects", "sites", "surveys", "lithologies", "pressures", "saved_pages")


def daily_requests(connection: Connection) -> list[dict[str, Any]]:
    return _rows(
        connection,
        """
        SELECT days.day, count(logs.id) AS requests, count(logs.id) FILTER (WHERE logs.status_code >= 500) AS server_errors
        FROM generate_series(date_trunc('day', now()) - make_interval(days => :days - 1), date_trunc('day', now()),
                             interval '1 day') AS days(day)
        LEFT JOIN usage_logs logs ON logs.created_at >= days.day AND logs.created_at < days.day + interval '1 day'
        GROUP BY days.day
        ORDER BY days.day
        """,
        days=ACTIVITY_DAYS,
    )


def response_times(connection: Connection) -> dict[str, Any]:
    return _rows(
        connection,
        """
        SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms) AS p50,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95
        FROM usage_logs WHERE created_at >= now() - make_interval(days => :days)
        """,
        days=ACTIVITY_DAYS,
    )[0]


def top_actions(connection: Connection) -> list[dict[str, Any]]:
    return _rows(
        connection,
        """
        SELECT action, count(*) AS requests
        FROM usage_logs
        WHERE created_at >= now() - make_interval(days => :days) AND action IS NOT NULL
        GROUP BY action
        ORDER BY requests DESC, action
        LIMIT :limit
        """,
        days=ACTIVITY_DAYS,
        limit=TOP_ACTIONS,
    )


# Volumes estimés par PostgreSQL (reltuples) : un count(*) sur les sondages prendrait plusieurs secondes.
def data_volumes(connection: Connection) -> list[dict[str, Any]]:
    return _rows(
        connection,
        """
        SELECT c.relname AS name, CASE WHEN c.reltuples < 0 THEN NULL ELSE c.reltuples::bigint END AS estimated_rows
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND c.relname = ANY (:tables)
        """,
        tables=list(VOLUME_TABLES),
    )
