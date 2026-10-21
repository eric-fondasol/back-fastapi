# Le SQL des affaires, dans la base métier (tables projects, sites, surveys et référentiels).
# Repris de DoctrineProjectRepository, DoctrineSurveyRepository, DoctrineSiteRepository et
# GeolocationSqlTranslator du back Symfony. Les fonctions reçoivent la connexion de la transaction
# ouverte par services.py.

import re
from typing import Any

from sqlalchemy import Connection, bindparam, text

from app.domains.projects.entities import (
    SORT_COLUMNS,
    SURVEY_DRIVEN_TYPE_IDS,
    Coordinates,
    EnteredPosition,
    GedFilter,
    GeolocationFilter,
    Project,
    SearchCriteria,
    Site,
    Survey,
    SurveyPresenceFilter,
    SurveyTally,
    stored_coordinates,
)

# Tri alphabétique français : sans tenir compte des accents ni de la casse (« abri », « École », « Zénith »).
SORT_COLLATION = "fr-x-icu"

PROJECT_COLUMNS = """
    p.id, p.name, p.city, p.city_agency, p.code_metier, p.client, p.uuid, p.externe_id, p.url_id,
    p.altitude, p.is_doc_ged, p.is_doc_ged_updated_by, p.is_doc_ged_updated_at, p.no_geo_project_reason_id, p.project_type_id, p.updated_at, p.user_email,
    ST_X(p.geometry) AS longitude, ST_Y(p.geometry) AS latitude,
    p.longitude_saisie, p.latitude_saisie, p.systeme_geo
"""

SURVEY_COLUMNS = """
    sv.id, sv.site_id, sv.city, sv.altitude, sv.depth_min, sv.depth_max, sv.no_geo_survey_reason_id,
    sv.updated_at, ST_X(sv.geometry) AS longitude, ST_Y(sv.geometry) AS latitude,
    sv.longitude_saisie, sv.latitude_saisie, sv.systeme_geo
"""

# Un sondage est traité s'il est positionné ou marqué non géolocalisable.
SURVEY_GEOLOCATED = "(sv.geometry IS NOT NULL OR sv.no_geo_survey_reason_id IS NOT NULL)"
TALLY_TOTAL = "COUNT(sv.id)"
TALLY_GEOLOCATED = f"COALESCE(SUM(CASE WHEN {SURVEY_GEOLOCATED} THEN 1 ELSE 0 END), 0)"
HAS_NO_GEO_REASON = "(p.no_geo_project_reason_id IS NOT NULL AND p.no_geo_project_reason_id != 0)"
HAS_NO_REASON = "(p.no_geo_project_reason_id IS NULL OR p.no_geo_project_reason_id = 0)"
SURVEY_DRIVEN = f"(COALESCE(p.project_type_id, 0) IN ({', '.join(map(str, SURVEY_DRIVEN_TYPE_IDS))}))"
HAS_POSITION = "p.geometry IS NOT NULL"
# Numéro réduit à ses lettres majuscules et chiffres : « 95.gt.25 » et « 95GT.25 » se valent.
# Même expression que l'index idx_projects_compact_id (migration 0002), sans quoi il ne sert pas.
COMPACT_PROJECT_ID = "regexp_replace(upper(p.id), '[^A-Z0-9]', '', 'g')"

TALLIED_PROJECTS = f"""
    SELECT {PROJECT_COLUMNS}, {TALLY_TOTAL} AS total, {TALLY_GEOLOCATED} AS geolocated
    FROM projects p
    LEFT JOIN sites s ON s.project_id = p.id
    LEFT JOIN surveys sv ON sv.site_id = s.id
"""


# Traduction SQL des filtres « selectedGeo » : même règle que entities.classify, appliquée au
# décompte des sondages (HAVING).
def geolocation_having(geolocation_filter: GeolocationFilter) -> str:
    return {
        GeolocationFilter.GEOLOCATED: (
            f"({HAS_NO_REASON} AND (({SURVEY_DRIVEN} AND {TALLY_TOTAL} > 0 AND {TALLY_TOTAL} = {TALLY_GEOLOCATED})"
            f" OR (NOT {SURVEY_DRIVEN} AND {HAS_POSITION} AND ({TALLY_TOTAL} = 0 OR {TALLY_TOTAL} = {TALLY_GEOLOCATED}))))"
        ),
        GeolocationFilter.TO_GEOLOCATE: f"({HAS_NO_REASON} AND NOT {HAS_POSITION} AND NOT {SURVEY_DRIVEN})",
        GeolocationFilter.SURVEYS_TO_GEOLOCATE: (
            f"({HAS_NO_REASON} AND ({HAS_POSITION} OR {SURVEY_DRIVEN}) AND {TALLY_TOTAL} > {TALLY_GEOLOCATED})"
        ),
        GeolocationFilter.IMPOSSIBLE: f"({HAS_NO_GEO_REASON} OR ({SURVEY_DRIVEN} AND {TALLY_TOTAL} = 0))",
    }[geolocation_filter]


def survey_presence_having(survey_filter: SurveyPresenceFilter) -> str:
    return f"{TALLY_TOTAL} > 0" if survey_filter is SurveyPresenceFilter.WITH_SURVEYS else f"{TALLY_TOTAL} = 0"


# Recherche paginée de l'écran Projets. Renvoie les affaires de la page avec leur décompte, et le
# total (0 si count_total est faux, comme le mode « withoutPaginate » de l'ancien contrat).
def search(connection: Connection, criteria: SearchCriteria) -> tuple[list[tuple[Project, SurveyTally]], int]:
    where, parameters = _filters(criteria)
    having = []

    if criteria.geolocation_filter is not None:
        having.append(geolocation_having(criteria.geolocation_filter))
    if criteria.survey_filter is not None:
        having.append(survey_presence_having(criteria.survey_filter))

    order_by = _order_by(criteria)
    having_sql = f"HAVING {' AND '.join(having)}" if having else ""
    grouped = f"{TALLIED_PROJECTS} WHERE {where} GROUP BY p.id {having_sql}"
    page = {"limit": criteria.limit, "offset": criteria.offset}

    total = 0
    if criteria.count_total:
        count_sql = f"SELECT COUNT(*) FROM ({grouped}) AS matches" if having else f"SELECT COUNT(*) FROM projects p WHERE {where}"
        total = connection.execute(text(count_sql), parameters).scalar_one()

    # Sans filtre sur les sondages, la page est choisie avant de compter les sondages : seules ses
    # affaires sont jointes aux chantiers et sondages.
    if having:
        rows_sql = f"{grouped} ORDER BY {order_by} LIMIT :limit OFFSET :offset"
    else:
        rows_sql = f"""
            {TALLIED_PROJECTS}
            WHERE p.id IN (SELECT p.id FROM projects p WHERE {where} ORDER BY {order_by} LIMIT :limit OFFSET :offset)
            GROUP BY p.id
            ORDER BY {order_by}
        """

    rows = connection.execute(text(rows_sql), parameters | page).mappings()
    return [(_project(row), _tally(row)) for row in rows], total


def compact_project_number(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _filters(criteria: SearchCriteria) -> tuple[str, dict[str, Any]]:
    where, parameters = ["1 = 1"], {}

    if criteria.project_id is not None:
        where.append(f"{COMPACT_PROJECT_ID} LIKE :project_id")
        parameters["project_id"] = f"{compact_project_number(criteria.project_id)}%"
    if criteria.name is not None:
        where.append("LOWER(p.name) LIKE :name")
        parameters["name"] = f"%{criteria.name.lower()}%"
    if criteria.city is not None:
        where.append("UPPER(p.city) LIKE :city")
        parameters["city"] = f"{criteria.city.upper()}%"
    if criteria.city_agency is not None:
        where.append("p.city_agency = :city_agency")
        parameters["city_agency"] = criteria.city_agency
    if criteria.code_metier is not None:
        where.append("p.code_metier = :code_metier")
        parameters["code_metier"] = criteria.code_metier
    if criteria.client is not None:
        where.append("UPPER(p.client) LIKE :client")
        parameters["client"] = f"{criteria.client.upper()}%"
    if criteria.ged_filter is not None:
        where.append("p.is_doc_ged = :is_doc_ged")
        parameters["is_doc_ged"] = criteria.ged_filter is GedFilter.WITH_DOCUMENTS

    return " AND ".join(where), parameters


# Par numéro par défaut ; sur une autre colonne, valeurs absentes en dernier et égalités
# départagées par numéro croissant.
def _order_by(criteria: SearchCriteria) -> str:
    direction = "DESC" if criteria.descending else "ASC"
    column = SORT_COLUMNS[criteria.sort]

    if column is None:
        return f"p.id {direction}"

    return f'{column} COLLATE "{SORT_COLLATION}" {direction} NULLS LAST, p.id ASC'


# Affaires demandées avec leur décompte ; une affaire inconnue est simplement absente.
def projects_with_tallies(connection: Connection, ids: list[str]) -> list[tuple[Project, SurveyTally]]:
    if not ids:
        return []

    statement = text(f"{TALLIED_PROJECTS} WHERE p.id IN :ids GROUP BY p.id").bindparams(bindparam("ids", expanding=True))
    rows = connection.execute(statement, {"ids": list(dict.fromkeys(ids))}).mappings()
    return [(_project(row), _tally(row)) for row in rows]


def find_project(connection: Connection, project_id: str) -> Project | None:
    row = connection.execute(text(f"SELECT {PROJECT_COLUMNS} FROM projects p WHERE p.id = :id"), {"id": project_id}).mappings().first()
    return _project(row) if row else None


# Sondages d'une affaire (150 au plus), par identifiant. Pressions et lithologies ne sont pas
# lues : l'ancien contrat les renvoie vides (voir « Reste à faire » du front, point 10).
def find_project_by_externe_id(connection: Connection, externe_id: str) -> Project | None:
    row = connection.execute(
        text(f"SELECT {PROJECT_COLUMNS} FROM projects p WHERE p.externe_id = :externe_id LIMIT 1"), {"externe_id": externe_id}
    ).mappings().first()
    return _project(row) if row else None


def project_surveys(connection: Connection, project_id: str, limit: int) -> list[Survey]:
    rows = connection.execute(
        text(
            f"SELECT {SURVEY_COLUMNS} FROM surveys sv JOIN sites s ON s.id = sv.site_id "
            "WHERE s.project_id = :project_id ORDER BY sv.id ASC LIMIT :limit"
        ),
        {"project_id": project_id, "limit": limit},
    ).mappings()
    return [_survey(row) for row in rows]


def find_survey(connection: Connection, survey_id: str) -> Survey | None:
    row = connection.execute(text(f"SELECT {SURVEY_COLUMNS} FROM surveys sv WHERE sv.id = :id"), {"id": survey_id}).mappings().first()
    return _survey(row) if row else None


def project_sites(connection: Connection, project_id: str) -> list[Site]:
    rows = connection.execute(
        text("SELECT id, ST_X(geometry) AS longitude, ST_Y(geometry) AS latitude FROM sites WHERE project_id = :project_id ORDER BY id"),
        {"project_id": project_id},
    ).mappings()
    return [Site(row["id"], stored_coordinates(row["longitude"], row["latitude"])) for row in rows]


def update_project(connection: Connection, project: Project) -> None:
    connection.execute(
        text(
            f"""
            UPDATE projects
               SET geometry = {_point_sql("longitude", "latitude")},
                   no_geo_project_reason_id = :no_geo_reason_id,
                   altitude = :altitude,
                   updated_at = :updated_at
             WHERE id = :id
            """
        ),
        _position_parameters(project.coordinates)
        | {"id": project.id, "no_geo_reason_id": project.no_geo_reason_id, "altitude": project.altitude, "updated_at": project.updated_at},
    )


# Saisie manuelle de la présence de documents GED, tracée (qui, quand) ; updated_at n'est pas touché :
# il date la position de l'affaire.
def update_ged_presence(connection: Connection, project: Project) -> None:
    connection.execute(
        text(
            """
            UPDATE projects
               SET is_doc_ged = :is_doc_ged,
                   is_doc_ged_updated_by = :updated_by,
                   is_doc_ged_updated_at = :updated_at
             WHERE id = :id
            """
        ),
        {"id": project.id, "is_doc_ged": project.is_doc_ged, "updated_by": project.is_doc_ged_updated_by, "updated_at": project.is_doc_ged_updated_at},
    )


# Repositionner une affaire place tous ses chantiers au même endroit, marqués fiables.
def relocate_project_sites(connection: Connection, project_id: str, coordinates: Coordinates) -> None:
    connection.execute(
        text(
            "UPDATE sites SET geometry = ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326), fiability = 1, updated_at = NOW() "
            "WHERE project_id = :project_id"
        ),
        {"longitude": coordinates.longitude, "latitude": coordinates.latitude, "project_id": project_id},
    )


def update_survey(connection: Connection, survey: Survey) -> None:
    connection.execute(
        text(
            f"""
            UPDATE surveys
               SET geometry = {_point_sql("longitude", "latitude")},
                   no_geo_survey_reason_id = :no_geo_reason_id,
                   altitude = :altitude,
                   updated_at = :updated_at
             WHERE id = :id
            """
        ),
        _position_parameters(survey.coordinates)
        | {"id": survey.id, "no_geo_reason_id": survey.no_geo_reason_id, "altitude": survey.altitude, "updated_at": survey.updated_at},
    )


def insert_survey(connection: Connection, survey: Survey) -> None:
    connection.execute(
        text(
            f"INSERT INTO surveys (id, site_id, geometry, altitude, updated_at) "
            f"VALUES (:id, :site_id, {_point_sql('longitude', 'latitude')}, :altitude, :updated_at)"
        ),
        _position_parameters(survey.coordinates)
        | {"id": survey.id, "site_id": survey.site_id, "altitude": survey.altitude, "updated_at": survey.updated_at},
    )


def distinct_values(connection: Connection, column: str) -> list[str]:
    return [
        str(value)
        for value in connection.execute(
            text(f"SELECT DISTINCT {column} FROM projects WHERE {column} IS NOT NULL ORDER BY {column} ASC")
        ).scalars()
    ]


def labels(connection: Connection, table: str) -> list[tuple[int, str]]:
    return [(row.id, row.libelle) for row in connection.execute(text(f"SELECT id, libelle FROM {table} ORDER BY id ASC"))]


# Un point PostGIS, ou NULL si la position est absente (CASE évite ST_MakePoint(NULL, NULL)).
def _point_sql(longitude: str, latitude: str) -> str:
    return (
        f"CASE WHEN CAST(:{longitude} AS double precision) IS NULL THEN NULL "
        f"ELSE ST_SetSRID(ST_MakePoint(:{longitude}, :{latitude}), 4326) END"
    )


def _position_parameters(coordinates: Coordinates | None) -> dict[str, float | None]:
    if coordinates is None:
        return {"longitude": None, "latitude": None}

    return {"longitude": coordinates.longitude, "latitude": coordinates.latitude}


def _entered_position(row: Any) -> EnteredPosition:
    return EnteredPosition(row["longitude_saisie"], row["latitude_saisie"], row["systeme_geo"])


def _project(row: Any) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        coordinates=stored_coordinates(row["longitude"], row["latitude"]),
        no_geo_reason_id=row["no_geo_project_reason_id"],
        type_id=row["project_type_id"],
        city=row["city"],
        city_agency=row["city_agency"],
        code_metier=row["code_metier"],
        client=row["client"],
        uuid=row["uuid"],
        externe_id=row["externe_id"],
        url_id=row["url_id"],
        altitude=row["altitude"],
        is_doc_ged=bool(row["is_doc_ged"]),
        is_doc_ged_updated_by=row["is_doc_ged_updated_by"],
        is_doc_ged_updated_at=row["is_doc_ged_updated_at"],
        entered_position=_entered_position(row),
        user_email=row["user_email"],
        updated_at=row["updated_at"],
    )


def _survey(row: Any) -> Survey:
    return Survey(
        id=row["id"],
        site_id=row["site_id"],
        coordinates=stored_coordinates(row["longitude"], row["latitude"]),
        no_geo_reason_id=row["no_geo_survey_reason_id"],
        city=row["city"],
        altitude=row["altitude"],
        depth_min=row["depth_min"],
        depth_max=row["depth_max"],
        entered_position=_entered_position(row),
        updated_at=row["updated_at"],
    )


def _tally(row: Any) -> SurveyTally:
    return SurveyTally(int(row["total"]), int(row["geolocated"]))
