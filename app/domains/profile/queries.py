# Le SQL du profil : préférences (user_preferences) et favoris (user_favorite_*), dans la base métier.
# Chaque fonction reçoit la connexion de la transaction ouverte par services.py, pour que plusieurs
# écritures (import des favoris) soient validées ou annulées ensemble.

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, text

from app.domains.profile.entities import (
    FavoriteAddress,
    FavoriteCoordinates,
    FavoriteParcel,
    FavoriteQuote,
    MapLayerSetting,
    Preferences,
    UserLayer,
)

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


# Les affaires favorites sont rangées par id de l'entrepôt (projects.id depuis le schéma v3), mais l'API
# les désigne toujours par leur n° (project_number) : la traduction se fait ici.
def favorite_project_ids(connection: Connection, user_id: str) -> list[str]:
    return list(
        connection.execute(
            text(
                "SELECT project.project_number FROM user_favorite_projects favorite "
                "JOIN projects project ON project.id = favorite.project_id "
                "WHERE favorite.user_id = :user_id ORDER BY favorite.created_at, project.project_number"
            ),
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
    return connection.execute(text("SELECT 1 FROM projects WHERE project_number = :number"), {"number": project_id}).first() is not None


def add_favorite_project(connection: Connection, user_id: str, project_id: str, at: datetime) -> None:
    connection.execute(
        text(
            "INSERT INTO user_favorite_projects (user_id, project_id, created_at) "
            "SELECT :user_id, id, :at FROM projects WHERE project_number = :project_id ON CONFLICT DO NOTHING"
        ),
        {"user_id": user_id, "project_id": project_id, "at": at},
    )


def remove_favorite_project(connection: Connection, user_id: str, project_id: str) -> None:
    connection.execute(
        text(
            "DELETE FROM user_favorite_projects WHERE user_id = :user_id "
            "AND project_id IN (SELECT id FROM projects WHERE project_number = :project_id)"
        ),
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


# Favoris de recherche (migration 0030) : le plus récent en tête, comme les adresses.
# Ajouter un favori déjà présent ne change rien (ON CONFLICT DO NOTHING) : sa date reste celle du premier ajout.
SEARCH_FAVORITE_TABLES = ("user_favorite_quotes", "user_favorite_coordinates", "user_favorite_parcels")


def favorite_count(connection: Connection, table: str, user_id: str) -> int:
    if table not in SEARCH_FAVORITE_TABLES:
        raise ValueError(table)

    return connection.execute(text(f"SELECT count(*) FROM {table} WHERE user_id = :user_id"), {"user_id": user_id}).scalar_one()


def favorite_quotes(connection: Connection, user_id: str) -> list[FavoriteQuote]:
    rows = connection.execute(
        text(
            "SELECT quote_number, description, created_at FROM user_favorite_quotes "
            "WHERE user_id = :user_id ORDER BY created_at DESC, quote_number"
        ),
        {"user_id": user_id},
    ).mappings()
    return [FavoriteQuote(row["quote_number"], row["description"], row["created_at"].astimezone(UTC)) for row in rows]


def favorite_quote(connection: Connection, user_id: str, number: str) -> FavoriteQuote | None:
    return next((quote for quote in favorite_quotes(connection, user_id) if quote.number == number), None)


def add_favorite_quote(connection: Connection, user_id: str, quote: FavoriteQuote) -> None:
    connection.execute(
        text(
            "INSERT INTO user_favorite_quotes (user_id, quote_number, description, created_at) "
            "VALUES (:user_id, :number, :description, :at) ON CONFLICT DO NOTHING"
        ),
        {"user_id": user_id, "number": quote.number, "description": quote.description, "at": quote.created_at},
    )


def remove_favorite_quote(connection: Connection, user_id: str, number: str) -> None:
    connection.execute(
        text("DELETE FROM user_favorite_quotes WHERE user_id = :user_id AND quote_number = :number"),
        {"user_id": user_id, "number": number},
    )


def favorite_coordinates(connection: Connection, user_id: str) -> list[FavoriteCoordinates]:
    rows = connection.execute(
        text(
            "SELECT latitude, longitude, created_at FROM user_favorite_coordinates "
            "WHERE user_id = :user_id ORDER BY created_at DESC, latitude, longitude"
        ),
        {"user_id": user_id},
    ).mappings()
    return [FavoriteCoordinates(float(row["latitude"]), float(row["longitude"]), row["created_at"].astimezone(UTC)) for row in rows]


def favorite_position(connection: Connection, user_id: str, latitude: float, longitude: float) -> FavoriteCoordinates | None:
    return next(
        (
            position
            for position in favorite_coordinates(connection, user_id)
            if (position.latitude, position.longitude) == (latitude, longitude)
        ),
        None,
    )


def add_favorite_coordinates(connection: Connection, user_id: str, position: FavoriteCoordinates) -> None:
    connection.execute(
        text(
            "INSERT INTO user_favorite_coordinates (user_id, latitude, longitude, created_at) "
            "VALUES (:user_id, :latitude, :longitude, :at) ON CONFLICT DO NOTHING"
        ),
        {"user_id": user_id, "latitude": position.latitude, "longitude": position.longitude, "at": position.created_at},
    )


def remove_favorite_coordinates(connection: Connection, user_id: str, latitude: float, longitude: float) -> None:
    connection.execute(
        text("DELETE FROM user_favorite_coordinates WHERE user_id = :user_id AND latitude = :latitude AND longitude = :longitude"),
        {"user_id": user_id, "latitude": latitude, "longitude": longitude},
    )


PARCEL_COLUMNS = "country, reference, municipality_code, municipality_name, section, number, created_at"


def favorite_parcels(connection: Connection, user_id: str) -> list[FavoriteParcel]:
    rows = connection.execute(
        text(
            f"SELECT {PARCEL_COLUMNS} FROM user_favorite_parcels "
            "WHERE user_id = :user_id ORDER BY created_at DESC, country, reference"
        ),
        {"user_id": user_id},
    ).mappings()
    return [
        FavoriteParcel(
            row["country"],
            row["reference"],
            row["municipality_code"],
            row["municipality_name"],
            row["section"],
            row["number"],
            row["created_at"].astimezone(UTC),
        )
        for row in rows
    ]


def favorite_parcel(connection: Connection, user_id: str, country: str, reference: str) -> FavoriteParcel | None:
    return next(
        (parcel for parcel in favorite_parcels(connection, user_id) if (parcel.country, parcel.reference) == (country, reference)),
        None,
    )


def add_favorite_parcel(connection: Connection, user_id: str, parcel: FavoriteParcel) -> None:
    connection.execute(
        text(
            f"INSERT INTO user_favorite_parcels ({PARCEL_COLUMNS}, user_id) "
            "VALUES (:country, :reference, :municipality_code, :municipality_name, :section, :number, :at, :user_id) "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "user_id": user_id,
            "country": parcel.country,
            "reference": parcel.reference,
            "municipality_code": parcel.municipality_code,
            "municipality_name": parcel.municipality_name,
            "section": parcel.section,
            "number": parcel.number,
            "at": parcel.created_at,
        },
    )


def remove_favorite_parcel(connection: Connection, user_id: str, country: str, reference: str) -> None:
    connection.execute(
        text("DELETE FROM user_favorite_parcels WHERE user_id = :user_id AND country = :country AND reference = :reference"),
        {"user_id": user_id, "country": country, "reference": reference},
    )


# Depuis le schéma v3 (migration 0019), l'emprise d'un fichier n'est plus stockée : elle est calculée à
# l'import et renvoyée avec la couche ajoutée, seul moment où le front s'en sert (cadrage sur le fichier).
USER_LAYER_COLUMNS = "id, name, kind, url, params, created_at, original_name, style"


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
                (id, user_id, name, kind, url, params, geojson, original_name, created_at, updated_at)
            VALUES
                (:id, :user_id, :name, :kind, :url, CAST(:params AS jsonb), CAST(:geojson AS jsonb), :original_name, :at, :at)
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
    return UserLayer(
        str(row["id"]),
        row["name"],
        row["kind"],
        row["url"],
        dict(row["params"]),
        row["created_at"].astimezone(UTC),
        row["original_name"],
        None,
        style=dict(row["style"]),
    )


# La business unit n'est retenue que si le département Azure est un code connu de business_units.
def set_department(connection: Connection, user_id: str, department: str | None) -> None:
    connection.execute(
        text(
            """
            UPDATE users
            SET department = :department,
                business_unit_code = (SELECT code FROM business_units WHERE code = :department)
            WHERE id = :user_id
            """
        ),
        {"department": department, "user_id": user_id},
    )
