from typing import Literal, Optional

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.connexions import base_apisolscore

router = APIRouter()


class SurveyBounds(BaseModel):
    minLng: float
    maxLng: float
    minLat: float
    maxLat: float


class SurveyPosition(BaseModel):
    lon: float = Field(..., ge=-180, le=180)
    lat: float = Field(..., ge=-90, le=90)


class SurveyRequest(BaseModel):
    bounds: SurveyBounds
    position: Optional[SurveyPosition] = None


class PointFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict
    properties: dict


class FeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[PointFeature]


def feature_collection_sql(longitude: str, latitude: str, properties: str, source: str) -> str:
    return f"""
        SELECT json_build_object(
                   'type', 'FeatureCollection',
                   'features', COALESCE(json_agg(json_build_object(
                       'type', 'Feature',
                       'geometry', json_build_object(
                           'type', 'Point',
                           'coordinates', json_build_array(round({longitude}, 6)::float8, round({latitude}, 6)::float8)
                       ),
                       'properties', {properties}
                   )), '[]'::json)
               )::text
        {source}
          AND {longitude} BETWEEN CAST(:minLng AS numeric) AND CAST(:maxLng AS numeric)
          AND {latitude} BETWEEN CAST(:minLat AS numeric) AND CAST(:maxLat AS numeric)
    """


SITES = """
    FROM public.site s
    JOIN public.affaire a
        ON a.id = s.affaire_id
    WHERE s.latitude IS NOT NULL
      AND s.longitude IS NOT NULL
"""

SONDAGES = """
    FROM public.sondage
    WHERE localisation_longitude_xwgs84 IS NOT NULL
      AND localisation_latitude_ywgs84 IS NOT NULL
"""

SITES_SQL = feature_collection_sql("s.longitude", "s.latitude", "'{}'::json", SITES)

SITES_DETAILS_SQL = feature_collection_sql(
    "s.longitude",
    "s.latitude",
    "json_build_object('uuid', s.uuid, 'affaire_id', a.id, 'affaire_numero', a.numero, 'affaire_nom', a.nom)",
    SITES,
)

SONDAGES_SQL = feature_collection_sql("localisation_longitude_xwgs84", "localisation_latitude_ywgs84", "'{}'::json", SONDAGES)

SONDAGES_DETAILS_SQL = feature_collection_sql(
    "localisation_longitude_xwgs84",
    "localisation_latitude_ywgs84",
    """json_build_object(
        'id', id,
        'nom', nom,
        'site_uuid', site_uuid,
        'has_mesure_pressiometrique', COALESCE(has_mesure_pressiometrique, false)
    )""",
    SONDAGES,
)


def feature_collection(sql: str, bounds: SurveyBounds) -> Response:
    with base_apisolscore.connect() as connexion:
        contenu = connexion.execute(text(sql), bounds.model_dump()).scalar()

    return Response(contenu, media_type="application/json")


@router.post("/searchSitesByArea", response_model=FeatureCollection)
def search_sites_by_area(payload: SurveyRequest):
    return feature_collection(SITES_SQL, payload.bounds)


@router.post("/searchSitesByAreaDetails", response_model=FeatureCollection)
def search_sites_by_area_details(payload: SurveyRequest):
    return feature_collection(SITES_DETAILS_SQL, payload.bounds)


@router.post("/searchSurveysByArea", response_model=FeatureCollection)
def search_surveys_by_area(payload: SurveyRequest):
    return feature_collection(SONDAGES_SQL, payload.bounds)


@router.post("/searchSurveysByAreaDetails", response_model=FeatureCollection)
def search_surveys_by_area_details(payload: SurveyRequest):
    return feature_collection(SONDAGES_DETAILS_SQL, payload.bounds)
