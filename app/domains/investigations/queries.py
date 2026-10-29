# Le SQL des enquêtes enregistrées (saved_pages) et de leurs versions (saved_page_versions).
# Repris de DoctrineSavedPageRepository et DoctrineInvestigationVersionRepository du back Symfony.
# Les fonctions reçoivent la connexion de la transaction ouverte par services.py.

import math
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, bindparam, text

from app.core.errors import NotFound
from app.database.connection import fetch_rows
from app.domains.investigations.entities import Author, Investigation, Nearby, Summary, SurveyCounts, Version, has_coordinates

PAGE_COLUMNS = "id, uuid, project_ref, project_ref_commentaire, data"
VERSION_COLUMNS = "version.id, version.version, version.comment, version.user_id, version.author_name, version.created_at, version.updated_at"

# Sondage fiable : localisation_fiabilite = 1 dans l'entrepôt (1 à 3, sens non documenté ; 86 % des
# sondages valent 1). Hypothèse du 28/10/2026, à confirmer par le métier (geolocation_reliabilities).
RELIABLE_SURVEY_LOCATION = 1
EARTH_RADIUS_M = 6371000
METRES_PER_DEGREE = 111320

# Sondages fiables à moins de :radius mètres, comptés par type d'essai et tous types confondus. Le
# rectangle (index sur latitude, longitude) écarte d'abord l'essentiel, la distance de haversine tranche ensuite.
RELIABLE_SURVEYS_SQL = f"""
    SELECT count(*) FILTER (WHERE has_mesure_pressiometrique IS TRUE) AS pressiometric,
           count(*) FILTER (WHERE has_essai_penetro_dynamique IS TRUE) AS penetrometric,
           count(*) AS total
    FROM public.sondage
    WHERE localisation_latitude_ywgs84 BETWEEN CAST(:minLat AS numeric) AND CAST(:maxLat AS numeric)
      AND localisation_longitude_xwgs84 BETWEEN CAST(:minLng AS numeric) AND CAST(:maxLng AS numeric)
      AND localisation_fiabilite = {RELIABLE_SURVEY_LOCATION}
      AND deleted IS NOT TRUE
      AND 2 * {EARTH_RADIUS_M} * asin(sqrt(
            power(sin(radians(localisation_latitude_ywgs84::float8 - :latitude) / 2), 2)
            + cos(radians(:latitude)) * cos(radians(localisation_latitude_ywgs84::float8))
              * power(sin(radians(localisation_longitude_xwgs84::float8 - :longitude) / 2), 2)
          )) <= :radius
"""


def find(connection: Connection, page_uuid: str) -> Investigation | None:
    row = connection.execute(text(f"SELECT {PAGE_COLUMNS} FROM saved_pages WHERE uuid = :uuid"), {"uuid": page_uuid}).mappings().first()
    return _investigation(row) if row else None


# Enquêtes d'une affaire, de la plus ancienne à la plus récente.
def of_project(connection: Connection, project_ref: str) -> list[Investigation]:
    rows = connection.execute(
        text(f"SELECT {PAGE_COLUMNS} FROM saved_pages WHERE project_ref = :project_ref ORDER BY created_at ASC NULLS LAST, id ASC"),
        {"project_ref": project_ref},
    ).mappings()
    return [_investigation(row) for row in rows]


def create(connection: Connection, page_uuid: str, data: str, email: str, username: str | None, project_ref: str, name: str | None, at: datetime) -> None:
    connection.execute(
        text(
            """
            INSERT INTO saved_pages (uuid, data, email, username, project_ref, project_ref_commentaire, created_at, updated_at)
            VALUES (:uuid, :data, :email, :username, :project_ref, :name, :at, :at)
            """
        ),
        {"uuid": page_uuid, "data": data, "email": email, "username": username, "project_ref": project_ref, "name": name, "at": at},
    )


# saved_pages.data suit toujours la dernière version, pour les autres lecteurs de la table.
def replace_content(connection: Connection, page_id: int, data: str, at: datetime) -> None:
    connection.execute(text("UPDATE saved_pages SET data = :data, updated_at = :at WHERE id = :id"), {"data": data, "at": at, "id": page_id})


def rename(connection: Connection, page_id: int, name: str | None, at: datetime) -> None:
    connection.execute(
        text("UPDATE saved_pages SET project_ref_commentaire = :name, updated_at = :at WHERE id = :id"), {"name": name, "at": at, "id": page_id}
    )


# Verrouille l'enquête jusqu'à la fin de la transaction : deux enregistrements simultanés ne
# peuvent pas prendre le même numéro de version.
def lock(connection: Connection, page_uuid: str) -> int:
    page_id = connection.execute(text("SELECT id FROM saved_pages WHERE uuid = :uuid FOR UPDATE"), {"uuid": page_uuid}).scalar()

    if page_id is None:
        raise NotFound(f"Enquete introuvable : {page_uuid}")

    return page_id


def latest_number(connection: Connection, page_id: int) -> int:
    return connection.execute(
        text("SELECT COALESCE(MAX(version), 0) FROM saved_page_versions WHERE saved_page_id = :page"), {"page": page_id}
    ).scalar_one()


def reliable_surveys_around(longitude: float, latitude: float, radius_m: int) -> SurveyCounts:
    latitude_span = radius_m / METRES_PER_DEGREE
    longitude_span = latitude_span / max(math.cos(math.radians(latitude)), 0.01)
    _, rows = fetch_rows(
        RELIABLE_SURVEYS_SQL,
        minLat=latitude - latitude_span,
        maxLat=latitude + latitude_span,
        minLng=longitude - longitude_span,
        maxLng=longitude + longitude_span,
        longitude=longitude,
        latitude=latitude,
        radius=radius_m,
    )
    pressiometric, penetrometric, total = rows[0]
    return SurveyCounts(pressiometric, penetrometric, total)


def append_version(
    connection: Connection, page_id: int, data: str, comment: str | None, author: Author, at: datetime, fuseau_analysis: str | None
) -> Version:
    version_id = str(uuid.uuid4())
    connection.execute(
        text(
            """
            INSERT INTO saved_page_versions
                (id, saved_page_id, version, data, comment, user_id, author_name, created_at, updated_at, fuseau_analysis)
            VALUES (:id, :page, :version, :data, :comment, :user_id, :author, :at, :at, :fuseau_analysis)
            """
        ),
        {
            "fuseau_analysis": fuseau_analysis,
            "id": version_id,
            "page": page_id,
            "version": latest_number(connection, page_id) + 1,
            "data": data,
            "comment": comment,
            "user_id": author.user_id,
            "author": author.name,
            "at": at,
        },
    )
    return _by_id(connection, version_id)


def revise_version(
    connection: Connection,
    page_id: int,
    number: int,
    data: str,
    comment: str | None,
    author: Author,
    at: datetime,
    fuseau_analysis: str | None,
) -> Version:
    version_id = connection.execute(
        text(
            """
            UPDATE saved_page_versions
               SET data = :data, comment = :comment, user_id = :user_id, author_name = :author, updated_at = :at,
                   fuseau_analysis = :fuseau_analysis
             WHERE saved_page_id = :page AND version = :version
            RETURNING id
            """
        ),
        {
            "data": data,
            "comment": comment,
            "user_id": author.user_id,
            "author": author.name,
            "at": at,
            "page": page_id,
            "version": number,
            "fuseau_analysis": fuseau_analysis,
        },
    ).scalar_one()
    return _by_id(connection, str(version_id))


def latest_version(connection: Connection, page_uuid: str) -> Version | None:
    row = connection.execute(
        text(
            f"SELECT {VERSION_COLUMNS}, version.data FROM saved_page_versions version "
            "JOIN saved_pages page ON page.id = version.saved_page_id WHERE page.uuid = :uuid ORDER BY version.version DESC LIMIT 1"
        ),
        {"uuid": page_uuid},
    ).mappings().first()
    return _version(row) if row else None


def version(connection: Connection, page_uuid: str, number: int) -> Version | None:
    row = connection.execute(
        text(
            f"SELECT {VERSION_COLUMNS}, version.data FROM saved_page_versions version "
            "JOIN saved_pages page ON page.id = version.saved_page_id WHERE page.uuid = :uuid AND version.version = :version"
        ),
        {"uuid": page_uuid, "version": number},
    ).mappings().first()
    return _version(row) if row else None


# Versions de plusieurs enquêtes, sans leur contenu, de la plus récente à la plus ancienne.
def histories(connection: Connection, page_uuids: list[str]) -> dict[str, list[Version]]:
    found: dict[str, list[Version]] = {page_uuid: [] for page_uuid in page_uuids}

    if not page_uuids:
        return found

    statement = text(
        f"SELECT page.uuid AS page_uuid, {VERSION_COLUMNS} FROM saved_page_versions version "
        "JOIN saved_pages page ON page.id = version.saved_page_id WHERE page.uuid IN :uuids ORDER BY page.uuid, version.version DESC"
    ).bindparams(bindparam("uuids", expanding=True))

    for row in connection.execute(statement, {"uuids": page_uuids}).mappings():
        found[str(row["page_uuid"])].append(_version(row))

    return found


# Recherche par n° d'affaire ou par nom ; « % » et « _ » saisis sont cherchés tels quels.
def search(connection: Connection, query: str | None, limit: int) -> list[Summary]:
    condition, parameters = "", {"limit": limit}

    if query:
        condition = "WHERE project_ref ILIKE :pattern OR project_ref_commentaire ILIKE :pattern"
        parameters["pattern"] = f"%{_escape_like(query)}%"

    rows = connection.execute(
        text(
            f"SELECT uuid, project_ref, project_ref_commentaire, data FROM saved_pages {condition} "
            "ORDER BY project_ref ASC, project_ref_commentaire ASC LIMIT :limit"
        ),
        parameters,
    ).mappings()
    return [Summary(str(row["uuid"]), row["project_ref"], row["project_ref_commentaire"], has_coordinates(row["data"])) for row in rows]


# Enquêtes avec un n° d'affaire dont la position enregistrée (« coordinates » du contenu, texte JSON)
# est à moins de :radius mètres. Le contenu est relu à chaque appel, en json (plus rapide à lire que
# jsonb pour une seule clé) : environ 0,5 s pour 2 000 enquêtes, tant que saved_pages.data reste du
# texte (jsonb prévu par le schéma v3). Sans contrôle préalable du JSON, qui doublait la durée : un
# contenu illisible fait échouer la requête (aucun le 29/10/2026 ; le front n'affiche alors aucune suggestion).
NEARBY_SQL = f"""
    WITH positioned AS (
        SELECT uuid, project_ref, project_ref_commentaire,
               (point ->> 'lng')::float8 AS longitude,
               (point ->> 'lat')::float8 AS latitude
        FROM saved_pages
        CROSS JOIN LATERAL (SELECT data::json -> 'coordinates' AS point) parsed
        WHERE trim(coalesce(project_ref, '')) <> ''
          AND json_typeof(point -> 'lng') = 'number'
          AND json_typeof(point -> 'lat') = 'number'
    ), measured AS (
        SELECT *, 2 * {EARTH_RADIUS_M} * asin(sqrt(
                   power(sin(radians(latitude - :latitude) / 2), 2)
                   + cos(radians(:latitude)) * cos(radians(latitude)) * power(sin(radians(longitude - :longitude) / 2), 2)
               )) AS distance
        FROM positioned
        WHERE latitude BETWEEN :minLat AND :maxLat AND longitude BETWEEN :minLng AND :maxLng
    )
    SELECT uuid, project_ref, project_ref_commentaire, distance FROM measured
    WHERE distance <= :radius ORDER BY distance, project_ref LIMIT :limit
"""


def nearby(connection: Connection, longitude: float, latitude: float, radius_m: int, limit: int) -> list[Nearby]:
    latitude_span = radius_m / METRES_PER_DEGREE
    longitude_span = latitude_span / max(math.cos(math.radians(latitude)), 0.01)
    rows = connection.execute(
        text(NEARBY_SQL),
        {
            "longitude": longitude,
            "latitude": latitude,
            "minLat": latitude - latitude_span,
            "maxLat": latitude + latitude_span,
            "minLng": longitude - longitude_span,
            "maxLng": longitude + longitude_span,
            "radius": radius_m,
            "limit": limit,
        },
    ).mappings()
    return [Nearby(str(row["uuid"]), row["project_ref"], row["project_ref_commentaire"], round(row["distance"])) for row in rows]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _by_id(connection: Connection, version_id: str) -> Version:
    row = connection.execute(
        text(f"SELECT {VERSION_COLUMNS}, version.data FROM saved_page_versions version WHERE version.id = :id"), {"id": version_id}
    ).mappings().one()
    return _version(row)


def _investigation(row: Any) -> Investigation:
    return Investigation(row["id"], str(row["uuid"]), row["project_ref"], row["project_ref_commentaire"], row["data"])


def _version(row: Any) -> Version:
    return Version(
        id=str(row["id"]),
        number=row["version"],
        comment=row["comment"],
        author=Author(None if row["user_id"] is None else str(row["user_id"]), row["author_name"]),
        created_at=_utc(row["created_at"]),
        updated_at=_utc(row["updated_at"]),
        data=row.get("data"),
    )


def _utc(value: datetime | None) -> datetime | None:
    return value.astimezone(UTC) if value else None
