from collections.abc import Sequence
from sqlalchemy import Row
from app.database.connection import fetch_rows
from app.domains.map.schemas import Bounds

SITES = """
    FROM public.site s
    JOIN public.affaire a ON a.id = s.affaire_id
    WHERE s.latitude IS NOT NULL
      AND s.longitude IS NOT NULL
"""

SITE_PROPERTIES = """,
    s.uuid::text AS uuid,
    a.id::text AS affaire_id,
    a.numero AS affaire_numero,
    a.nom AS affaire_nom
"""

SURVEYS = """
    FROM public.sondage
    WHERE localisation_longitude_xwgs84 IS NOT NULL
      AND localisation_latitude_ywgs84 IS NOT NULL
"""

SURVEY_PROPERTIES = """,
    id::text AS id,
    nom,
    site_uuid::text AS site_uuid,
    COALESCE(has_mesure_pressiometrique, false) AS has_mesure_pressiometrique
"""


def points_sql(longitude: str, latitude: str, properties: str, source: str) -> str:
    return f"""
        SELECT round({longitude}, 6)::float8 AS longitude,
               round({latitude}, 6)::float8 AS latitude
               {properties}
        {source}
          AND {longitude} BETWEEN CAST(:minLng AS numeric) AND CAST(:maxLng AS numeric)
          AND {latitude} BETWEEN CAST(:minLat AS numeric) AND CAST(:maxLat AS numeric)
    """


SITES_SQL = points_sql("s.longitude", "s.latitude", "", SITES)
SITES_WITH_DETAILS_SQL = points_sql("s.longitude", "s.latitude", SITE_PROPERTIES, SITES)

SURVEYS_SQL = points_sql("localisation_longitude_xwgs84", "localisation_latitude_ywgs84", "", SURVEYS)
SURVEYS_WITH_DETAILS_SQL = points_sql(
    "localisation_longitude_xwgs84", "localisation_latitude_ywgs84", SURVEY_PROPERTIES, SURVEYS
)


def sites_in_area(bounds: Bounds, with_details: bool) -> tuple[list[str], Sequence[Row]]:
    return fetch_rows(SITES_WITH_DETAILS_SQL if with_details else SITES_SQL, **bounds.model_dump())


def surveys_in_area(bounds: Bounds, with_details: bool) -> tuple[list[str], Sequence[Row]]:
    return fetch_rows(SURVEYS_WITH_DETAILS_SQL if with_details else SURVEYS_SQL, **bounds.model_dump())
