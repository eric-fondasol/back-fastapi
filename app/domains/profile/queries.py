# Le SQL du profil : préférences (user_preferences) et favoris (user_favorite_*), dans la base métier.
# Chaque fonction reçoit la connexion de la transaction ouverte par services.py, pour que plusieurs
# écritures (import des favoris) soient validées ou annulées ensemble.

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, text

from app.domains.profile.entities import FavoriteAddress, MapLayerSetting, Preferences, UserLayer

ADDRESS_COLUMNS = (
    "id, external_id, label, name, context, kind, ST_X(geometry) AS longitude, ST_Y(geometry) AS latitude, created_at"
)


def preferences_of(connection: Connection, user_id: str) -> Preferences:
    row = connection.execute(
        text(
            "SELECT locale, theme, default_territory, map_style, map_layers, extra "
            "FROM user_preferences WHERE user_id = :user_id"
        ),
        {"user_id": user_id},
    ).mappings().first()

    if row is None:
        return Preferences()

    # map_layers est stocké en snake_case (layer_id) : reconverti vers le format de l'API.
    layers = [
        MapLayerSetting.of({"layerId": layer["layer_id"], "visible": layer["visible"], "opacity": layer["opacity"]})
        for layer in row["map_layers"]
    ]
    return Preferences(row["locale"], row["theme"], row["default_territory"], row["map_style"], layers, row["extra"])


def save_preferences(connection: Connection, user_id: str, preferences: Preferences, at: datetime) -> None:
    layers = [
        {"layer_id": layer.layer_id, "visible": layer.visible, "opacity": layer.opacity}
        for layer in preferences.map_layers
    ]
    connection.execute(
        text(
            """
            INSERT INTO user_preferences (user_id, locale, theme, default_territory, map_style, map_layers, extra, updated_at)
            VALUES (:user_id, :locale, :theme, :default_territory, :map_style,
                    CAST(:map_layers AS jsonb), CAST(:extra AS jsonb), :at)
            ON CONFLICT (user_id) DO UPDATE
                SET locale = EXCLUDED.locale,
                    theme = EXCLUDED.theme,
                    default_territory = EXCLUDED.default_territory,
                    map_style = EXCLUDED.map_style,
                    map_layers = EXCLUDED.map_layers,
                    extra = EXCLUDED.extra,
                    updated_at = EXCLUDED.updated_at
            """
        ),
        {
            "user_id": user_id,
            "locale": preferences.locale,
            "theme": preferences.theme,
            "default_territory": preferences.default_territory,
            "map_style": preferences.map_style,
            "map_layers": json.dumps(layers),
            "extra": json.dumps(preferences.extra),
            "at": at,
        },
    )


def favorite_project_ids(connection: Connection, user_id: str) -> list[str]:
    return list(
        connection.execute(
            text("SELECT project_id FROM user_favorite_projects WHERE user_id = :user_id ORDER BY created_at, project_id"),
            {"user_id": user_id},
        ).scalars()
    )


def favorite_layer_ids(connection: Connection, user_id: str) -> list[str]:
    return list(
        connection.execute(
            text("SELECT layer_id FROM user_favorite_layers WHERE user_id = :user_id ORDER BY created_at, layer_id"),
            {"user_id": user_id},
        ).scalars()
    )


def favorite_addresses(connection: Connection, user_id: str) -> list[FavoriteAddress]:
    rows = connection.execute(
        text(f"SELECT {ADDRESS_COLUMNS} FROM user_favorite_addresses WHERE user_id = :user_id ORDER BY created_at DESC, label"),
        {"user_id": user_id},
    ).mappings()
    return [_address(row) for row in rows]


def project_exists(connection: Connection, project_id: str) -> bool:
    return connection.execute(text("SELECT 1 FROM projects WHERE id = :id"), {"id": project_id}).first() is not None


def add_favorite_project(connection: Connection, user_id: str, project_id: str, at: datetime) -> None:
    connection.execute(
        text(
            "INSERT INTO user_favorite_projects (user_id, project_id, created_at) "
            "VALUES (:user_id, :project_id, :at) ON CONFLICT DO NOTHING"
        ),
        {"user_id": user_id, "project_id": project_id, "at": at},
    )


def remove_favorite_project(connection: Connection, user_id: str, project_id: str) -> None:
    connection.execute(
        text("DELETE FROM user_favorite_projects WHERE user_id = :user_id AND project_id = :project_id"),
        {"user_id": user_id, "project_id": project_id},
    )


def add_favorite_layer(connection: Connection, user_id: str, layer_id: str, at: datetime) -> None:
    connection.execute(
        text(
            "INSERT INTO user_favorite_layers (user_id, layer_id, created_at) "
            "VALUES (:user_id, :layer_id, :at) ON CONFLICT DO NOTHING"
        ),
        {"user_id": user_id, "layer_id": layer_id, "at": at},
    )


def remove_favorite_layer(connection: Connection, user_id: str, layer_id: str) -> None:
    connection.execute(
        text("DELETE FROM user_favorite_layers WHERE user_id = :user_id AND layer_id = :layer_id"),
        {"user_id": user_id, "layer_id": layer_id},
    )


def favorite_address_count(connection: Connection, user_id: str) -> int:
    return connection.execute(
        text("SELECT count(*) FROM user_favorite_addresses WHERE user_id = :user_id"), {"user_id": user_id}
    ).scalar_one()


def favorite_address_by_external_id(connection: Connection, user_id: str, external_id: str) -> FavoriteAddress | None:
    row = connection.execute(
        text(f"SELECT {ADDRESS_COLUMNS} FROM user_favorite_addresses WHERE user_id = :user_id AND external_id = :external_id"),
        {"user_id": user_id, "external_id": external_id},
    ).mappings().first()
    return _address(row) if row else None


def add_favorite_address(connection: Connection, user_id: str, address: FavoriteAddress) -> None:
    connection.execute(
        text(
            """
            INSERT INTO user_favorite_addresses (id, user_id, external_id, label, name, context, kind, geometry, created_at)
            VALUES (:id, :user_id, :external_id, :label, :name, :context, :kind,
                    ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326), :created_at)
            ON CONFLICT (user_id, external_id) DO NOTHING
            """
        ),
        {
            "id": address.id,
            "user_id": user_id,
            "external_id": address.external_id,
            "label": address.label,
            "name": address.name,
            "context": address.context,
            "kind": address.kind,
            "longitude": address.longitude,
            "latitude": address.latitude,
            "created_at": address.created_at,
        },
    )


# Renvoie False si l'adresse n'existe pas ou appartient à un autre agent.
def remove_favorite_address(connection: Connection, user_id: str, address_id: str) -> bool:
    result = connection.execute(
        text("DELETE FROM user_favorite_addresses WHERE user_id = :user_id AND id = :id"),
        {"user_id": user_id, "id": address_id},
    )
    return result.rowcount > 0


def _address(row: Any) -> FavoriteAddress:
    return FavoriteAddress(
        str(row["id"]),
        row["external_id"],
        row["label"],
        row["name"],
        row["context"],
        row["kind"],
        float(row["longitude"]),
        float(row["latitude"]),
        # Rendu en UTC, quel que soit le fuseau de la session PostgreSQL.
        row["created_at"].astimezone(UTC),
    )


USER_LAYER_COLUMNS = "id, name, kind, url, params, created_at, original_name, west, south, east, north, style"


def user_layers(connection: Connection, user_id: str) -> list[UserLayer]:
    rows = connection.execute(
        text(f"SELECT {USER_LAYER_COLUMNS} FROM user_layers WHERE user_id = :user_id ORDER BY lower(name), created_at"),
        {"user_id": user_id},
    ).mappings()
    return [_user_layer(row) for row in rows]


def user_layer_count(connection: Connection, user_id: str) -> int:
    return connection.execute(text("SELECT count(*) FROM user_layers WHERE user_id = :user_id"), {"user_id": user_id}).scalar_one()


def add_user_layer(connection: Connection, user_id: str, layer: UserLayer) -> None:
    connection.execute(
        text(
            """
            INSERT INTO user_layers
                (id, user_id, name, kind, url, params, geojson, original_name, west, south, east, north, created_at, updated_at)
            VALUES
                (:id, :user_id, :name, :kind, :url, CAST(:params AS jsonb), CAST(:geojson AS jsonb), :original_name,
                 :west, :south, :east, :north, :at, :at)
            """
        ),
        {
            "id": layer.id,
            "user_id": user_id,
            "name": layer.name,
            "kind": layer.kind,
            "url": layer.url,
            "params": json.dumps(layer.params),
            "geojson": None if layer.geojson is None else json.dumps(layer.geojson, separators=(",", ":")),
            "original_name": layer.original_name,
            **dict(zip(["west", "south", "east", "north"], layer.bounds or (None, None, None, None))),
            "at": layer.created_at,
        },
    )


# None si la couche n'existe pas, n'est pas un fichier ou appartient à un autre agent.
def user_layer_geojson(connection: Connection, user_id: str, layer_uuid: str) -> dict[str, Any] | None:
    return connection.execute(
        text("SELECT geojson FROM user_layers WHERE user_id = :user_id AND id = :id AND kind = 'file'"),
        {"user_id": user_id, "id": layer_uuid},
    ).scalar_one_or_none()


# None si la couche n'existe pas ou appartient à un autre agent.
def revise_user_layer(
    connection: Connection, user_id: str, layer_uuid: str, name: str | None, style: dict[str, Any] | None, at: datetime
) -> UserLayer | None:
    row = connection.execute(
        text(
            "UPDATE user_layers SET name = COALESCE(:name, name), style = COALESCE(CAST(:style AS jsonb), style), "
            f"updated_at = :at WHERE user_id = :user_id AND id = :id RETURNING {USER_LAYER_COLUMNS}"
        ),
        {"user_id": user_id, "id": layer_uuid, "name": name, "style": None if style is None else json.dumps(style), "at": at},
    ).mappings().first()
    return _user_layer(row) if row else None


# Supprime la couche, puis ses traces dans les favoris et dans « Mes couches » (map_layers).
def remove_user_layer(connection: Connection, user_id: str, layer_uuid: str, layer_id: str) -> bool:
    removed = connection.execute(
        text("DELETE FROM user_layers WHERE user_id = :user_id AND id = :id"), {"user_id": user_id, "id": layer_uuid}
    ).rowcount > 0

    if removed:
        remove_favorite_layer(connection, user_id, layer_id)
        connection.execute(
            text(
                """
                UPDATE user_preferences
                SET map_layers = COALESCE(
                    (SELECT jsonb_agg(layer) FROM jsonb_array_elements(map_layers) AS layer WHERE layer->>'layer_id' <> :layer_id),
                    '[]'::jsonb)
                WHERE user_id = :user_id
                """
            ),
            {"user_id": user_id, "layer_id": layer_id},
        )

    return removed


def _user_layer(row: Any) -> UserLayer:
    bounds = (row["west"], row["south"], row["east"], row["north"])
    return UserLayer(
        str(row["id"]),
        row["name"],
        row["kind"],
        row["url"],
        dict(row["params"]),
        row["created_at"].astimezone(UTC),
        row["original_name"],
        None if None in bounds else bounds,
        style=dict(row["style"]),
    )


def set_department(connection: Connection, user_id: str, service_id: str | None) -> None:
    connection.execute(text("UPDATE users SET service_id = :service_id WHERE id = :user_id"), {"service_id": service_id, "user_id": user_id})
