# Le SQL des affaires, dans la base métier (tables projects, sites, surveys et référentiels).
# Repris de DoctrineProjectRepository, DoctrineSurveyRepository, DoctrineSiteRepository et
# GeolocationSqlTranslator du back Symfony. Les fonctions reçoivent la connexion de la transaction
# ouverte par services.py.

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, bindparam, text

from app.domains.projects.entities import (
    SORT_COLUMNS,
    SURVEY_DRIVEN_TYPE_IDS,
    Coordinates,
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

# Depuis le schéma v3 (migrations 0015 et 0016), projects.id est l'id de l'entrepôt et le n° d'affaire est
# dans project_number : l'API désigne toujours une affaire par son n°, l'id sert aux jointures (« key »).
# La position et l'altitude sont celles des sites : celle du premier site positionné, de préférence celui
# qui porte le n° de l'affaire (277 000 affaires sur 303 000 le 29/10/2026). L'agence est le libellé de la
# business unit, les métiers sont ceux de project_business_lines, la trace GED la dernière de docs_ged_changes.
PROJECT_JOINS = """
    LEFT JOIN business_units unit ON unit.code = p.business_unit_code
    LEFT JOIN LATERAL (
        SELECT string_agg(line.business_line_code, ', ' ORDER BY line.business_line_code) AS codes
        FROM project_business_lines line WHERE line.project_id = p.id
    ) lines ON true
    LEFT JOIN LATERAL (
        SELECT site.geometry, site.altitude FROM sites site WHERE site.project_id = p.id
        ORDER BY site.geometry IS NULL, site.id = p.project_number DESC, site.id LIMIT 1
    ) position ON true
    LEFT JOIN LATERAL (
        SELECT change.user_email, change.changed_at FROM docs_ged_changes change
        WHERE change.project_id = p.id ORDER BY change.changed_at DESC LIMIT 1
    ) ged ON true
"""

PROJECT_COLUMNS = """
    p.id AS key, p.project_number, p.project_description, p.city, unit.libelle AS agency, lines.codes AS business_codes,
    p.client, p.is_doc_ged, p.no_geo_project_reason_id, p.project_type_id, p.updated_at,
    ST_X(position.geometry) AS longitude, ST_Y(position.geometry) AS latitude, position.altitude,
    ged.user_email AS ged_updated_by, ged.changed_at AS ged_updated_at
"""

SURVEY_COLUMNS = """
    sv.id, sv.site_id, sv.altitude, sv.depth_min, sv.depth_max, sv.no_geo_survey_reason_id,
    sv.updated_at, ST_X(sv.geometry) AS longitude, ST_Y(sv.geometry) AS latitude
"""

# Un sondage est traité s'il est positionné ou marqué non géolocalisable.
SURVEY_GEOLOCATED = "(sv.geometry IS NOT NULL OR sv.no_geo_survey_reason_id IS NOT NULL)"
TALLY_TOTAL = "COUNT(sv.id)"
TALLY_GEOLOCATED = f"COALESCE(SUM(CASE WHEN {SURVEY_GEOLOCATED} THEN 1 ELSE 0 END), 0)"
# Décompte des sondages d'une affaire déjà choisie (page de résultats, fiche, statuts).
SURVEY_TALLY = f"""
    LEFT JOIN LATERAL (
        SELECT {TALLY_TOTAL} AS total, {TALLY_GEOLOCATED} AS geolocated
        FROM sites s JOIN surveys sv ON sv.site_id = s.id WHERE s.project_id = p.id
    ) tally ON true
"""
# Filtres sur les sondages et la position : toutes les affaires sont regroupées avec leurs sites et
# sondages (GROUP BY p.id), comme avant le schéma v3 ; seules les affaires retenues sont ensuite détaillées.
GROUPED_SITES_AND_SURVEYS = "LEFT JOIN sites s ON s.project_id = p.id LEFT JOIN surveys sv ON sv.site_id = s.id"
HAS_NO_GEO_REASON = "(p.no_geo_project_reason_id IS NOT NULL AND p.no_geo_project_reason_id != 0)"
HAS_NO_REASON = "(p.no_geo_project_reason_id IS NULL OR p.no_geo_project_reason_id = 0)"
SURVEY_DRIVEN = f"(COALESCE(p.project_type_id, 0) IN ({', '.join(map(str, SURVEY_DRIVEN_TYPE_IDS))}))"
HAS_POSITION = "bool_or(s.geometry IS NOT NULL)"
# Numéro réduit à ses lettres majuscules et chiffres : « 95.gt.25 » et « 95GT.25 » se valent.
# Même expression que l'index idx_projects_compact_id (migration 0002), sans quoi il ne sert pas.
COMPACT_PROJECT_ID = "regexp_replace(upper(p.project_number), '[^A-Z0-9]', '', 'g')"

PROJECTS = f"SELECT {PROJECT_COLUMNS} FROM projects p {PROJECT_JOINS}"
TALLIED_PROJECTS = f"SELECT {PROJECT_COLUMNS}, tally.total, tally.geolocated FROM projects p {PROJECT_JOINS} {SURVEY_TALLY}"
# Ce qu'il faut joindre pour filtrer ou trier sans détailler les affaires : l'agence (filtre et tri).
SEARCH_JOINS = "LEFT JOIN business_units unit ON unit.code = p.business_unit_code"


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
# total (0 si count_total est faux, comme le mode « withoutPaginate » de l'ancien contrat). La page est
# choisie d'abord (sur les affaires regroupées avec leurs sondages s'il y a un filtre sur eux), puis
# seules ses affaires sont détaillées (position, métiers, trace GED, décompte).
def search(connection: Connection, criteria: SearchCriteria) -> tuple[list[tuple[Project, SurveyTally]], int]:
    where, parameters = _filters(criteria)
    having = []

    if criteria.geolocation_filter is not None:
        having.append(geolocation_having(criteria.geolocation_filter))
    if criteria.survey_filter is not None:
        having.append(survey_presence_having(criteria.survey_filter))

    order_by = _order_by(criteria)
    matches = f"SELECT p.id FROM projects p {SEARCH_JOINS} WHERE {where}"

    if having:
        matches = (
            f"SELECT p.id FROM projects p {SEARCH_JOINS} {GROUPED_SITES_AND_SURVEYS} "
            f"WHERE {where} GROUP BY p.id, unit.libelle HAVING {' AND '.join(having)}"
        )

    total = 0
    if criteria.count_total:
        total = connection.execute(text(f"SELECT COUNT(*) FROM ({matches}) AS matches"), parameters).scalar_one()

    page_ids = f"{matches} ORDER BY {order_by} LIMIT :limit OFFSET :offset"
    rows = connection.execute(
        text(f"{TALLIED_PROJECTS} WHERE p.id IN ({page_ids}) ORDER BY {order_by}"),
        parameters | {"limit": criteria.limit, "offset": criteria.offset},
    ).mappings()
    return [(_project(row), _tally(row)) for row in rows], total


def compact_project_number(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _filters(criteria: SearchCriteria) -> tuple[str, dict[str, Any]]:
    where, parameters = ["1 = 1"], {}

    if criteria.project_id is not None:
        where.append(f"{COMPACT_PROJECT_ID} LIKE :project_id")
        parameters["project_id"] = f"{compact_project_number(criteria.project_id)}%"
    if criteria.name is not None:
        where.append("LOWER(p.project_description) LIKE :name")
        parameters["name"] = f"%{criteria.name.lower()}%"
    if criteria.city is not None:
        where.append("UPPER(p.city) LIKE :city")
        parameters["city"] = f"{criteria.city.upper()}%"
    if criteria.city_agency is not None:
        where.append("unit.libelle = :city_agency")
        parameters["city_agency"] = criteria.city_agency
    if criteria.code_metier is not None:
        where.append(
            "EXISTS (SELECT 1 FROM project_business_lines line WHERE line.project_id = p.id AND line.business_line_code = :code_metier)"
        )
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
        return f"p.project_number {direction}"

    return f'{column} COLLATE "{SORT_COLLATION}" {direction} NULLS LAST, p.project_number ASC'


# Affaires demandées (par n°) avec leur décompte ; une affaire inconnue est simplement absente.
def projects_with_tallies(connection: Connection, ids: list[str]) -> list[tuple[Project, SurveyTally]]:
    if not ids:
        return []

    statement = text(f"{TALLIED_PROJECTS} WHERE p.project_number IN :ids").bindparams(bindparam("ids", expanding=True))
    rows = connection.execute(statement, {"ids": list(dict.fromkeys(ids))}).mappings()
    return [(_project(row), _tally(row)) for row in rows]


def find_project(connection: Connection, project_number: str) -> Project | None:
    row = connection.execute(text(f"{PROJECTS} WHERE p.project_number = :number"), {"number": project_number}).mappings().first()
    return _project(row) if row else None


# L'identifiant GED d'une affaire (ancien externe_id) est l'id de l'entrepôt, devenu projects.id.
def find_project_by_ged_id(connection: Connection, ged_id: str) -> Project | None:
    row = connection.execute(text(f"{PROJECTS} WHERE p.id = :key"), {"key": ged_id}).mappings().first()
    return _project(row) if row else None


# Sondages d'une affaire (150 au plus), par identifiant. Pressions et lithologies ne sont pas
# lues : l'ancien contrat les renvoie vides (voir « Reste à faire » du front, point 10).
def project_surveys(connection: Connection, project_key: str, limit: int) -> list[Survey]:
    rows = connection.execute(
        text(
            f"SELECT {SURVEY_COLUMNS} FROM surveys sv JOIN sites s ON s.id = sv.site_id "
            "WHERE s.project_id = :project_key ORDER BY sv.id ASC LIMIT :limit"
        ),
        {"project_key": project_key, "limit": limit},
    ).mappings()
    return [_survey(row) for row in rows]


def find_survey(connection: Connection, survey_id: str) -> Survey | None:
    row = connection.execute(text(f"SELECT {SURVEY_COLUMNS} FROM surveys sv WHERE sv.id = :id"), {"id": survey_id}).mappings().first()
    return _survey(row) if row else None


def project_sites(connection: Connection, project_key: str) -> list[Site]:
    rows = connection.execute(
        text("SELECT id, ST_X(geometry) AS longitude, ST_Y(geometry) AS latitude FROM sites WHERE project_id = :project_key ORDER BY id"),
        {"project_key": project_key},
    ).mappings()
    return [Site(row["id"], stored_coordinates(row["longitude"], row["latitude"])) for row in rows]


def update_project(connection: Connection, project: Project) -> None:
    connection.execute(
        text("UPDATE projects SET no_geo_project_reason_id = :no_geo_reason_id, updated_at = :updated_at WHERE id = :key"),
        {"key": project.key, "no_geo_reason_id": project.no_geo_reason_id, "updated_at": project.updated_at},
    )


# Saisie manuelle de la présence de documents GED, tracée dans docs_ged_changes (qui, quand, avant,
# après) ; updated_at n'est pas touché : il date la position de l'affaire.
def update_ged_presence(connection: Connection, project: Project, previous: bool) -> None:
    connection.execute(text("UPDATE projects SET is_doc_ged = :is_doc_ged WHERE id = :key"), {"key": project.key, "is_doc_ged": project.is_doc_ged})
    connection.execute(
        text(
            "INSERT INTO docs_ged_changes (project_id, is_doc_ged_old_value, is_doc_ged_new_value, user_email, changed_at) "
            "VALUES (:key, :previous, :is_doc_ged, :updated_by, :updated_at)"
        ),
        {
            "key": project.key,
            "previous": previous,
            "is_doc_ged": project.is_doc_ged,
            "updated_by": project.is_doc_ged_updated_by,
            "updated_at": None if project.is_doc_ged_updated_at is None else project.is_doc_ged_updated_at.replace(tzinfo=UTC),
        },
    )


# Repositionner une affaire place tous ses chantiers au même endroit, marqués fiables. Une affaire sans
# chantier en reçoit un, sous son n° (comme la plupart des chantiers) : sans lui, sa position serait perdue.
def relocate_project_sites(connection: Connection, project: Project, coordinates: Coordinates | None, altitude: float | None) -> None:
    if coordinates is not None:
        connection.execute(
            text(
                "INSERT INTO sites (id, project_id) SELECT :number, CAST(:key AS varchar) "
                "WHERE NOT EXISTS (SELECT 1 FROM sites WHERE project_id = CAST(:key AS varchar)) ON CONFLICT (id) DO NOTHING"
            ),
            {"number": project.id, "key": project.key},
        )
        connection.execute(
            text(
                "UPDATE sites SET geometry = ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326), longitude = :longitude, "
                "latitude = :latitude, fiab_geo_sites = 1 WHERE project_id = :key"
            ),
            {"longitude": coordinates.longitude, "latitude": coordinates.latitude, "key": project.key},
        )

    if altitude is not None:
        connection.execute(text("UPDATE sites SET altitude = :altitude WHERE project_id = :key"), {"altitude": altitude, "key": project.key})


def update_survey(connection: Connection, survey: Survey) -> None:
    connection.execute(
        text(
            f"""
            UPDATE surveys
               SET geometry = {_point_sql("longitude", "latitude")},
                   longitude = :longitude,
                   latitude = :latitude,
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
            f"INSERT INTO surveys (id, site_id, name, geometry, longitude, latitude, altitude, updated_at) "
            f"VALUES (:id, :site_id, :name, {_point_sql('longitude', 'latitude')}, :longitude, :latitude, :altitude, :updated_at)"
        ),
        _position_parameters(survey.coordinates)
        | {"id": survey.id, "site_id": survey.site_id, "name": survey.name, "altitude": survey.altitude, "updated_at": survey.updated_at},
    )


# Valeurs proposées par les filtres de l'écran Projets : métiers et agences effectivement portés par des affaires.
def business_codes(connection: Connection) -> list[str]:
    return list(connection.execute(text("SELECT DISTINCT business_line_code FROM project_business_lines ORDER BY 1")).scalars())


def agencies(connection: Connection) -> list[str]:
    return list(
        connection.execute(
            text(
                "SELECT DISTINCT unit.libelle FROM business_units unit "
                "WHERE unit.libelle IS NOT NULL AND EXISTS (SELECT 1 FROM projects p WHERE p.business_unit_code = unit.code) ORDER BY 1"
            )
        ).scalars()
    )


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


def _project(row: Any) -> Project:
    return Project(
        id=row["project_number"],
        key=row["key"],
        name=row["project_description"],
        coordinates=stored_coordinates(row["longitude"], row["latitude"]),
        no_geo_reason_id=row["no_geo_project_reason_id"],
        type_id=row["project_type_id"],
        city=row["city"],
        city_agency=row["agency"],
        code_metier=row["business_codes"],
        client=row["client"],
        externe_id=row["key"],
        altitude=row["altitude"],
        is_doc_ged=bool(row["is_doc_ged"]),
        is_doc_ged_updated_by=row["ged_updated_by"],
        is_doc_ged_updated_at=_naive_utc(row["ged_updated_at"]),
        updated_at=row["updated_at"],
    )


def _survey(row: Any) -> Survey:
    return Survey(
        id=row["id"],
        site_id=row["site_id"],
        coordinates=stored_coordinates(row["longitude"], row["latitude"]),
        no_geo_reason_id=row["no_geo_survey_reason_id"],
        altitude=row["altitude"],
        depth_min=row["depth_min"],
        depth_max=row["depth_max"],
        updated_at=row["updated_at"],
    )


# Les dates des affaires sont manipulées en UTC sans fuseau (schemas._date) ; docs_ged_changes, elle, a un fuseau.
def _naive_utc(value: datetime | None) -> datetime | None:
    return value.astimezone(UTC).replace(tzinfo=None) if value is not None and value.tzinfo is not None else value


def _tally(row: Any) -> SurveyTally:
    return SurveyTally(int(row["total"]), int(row["geolocated"]))
