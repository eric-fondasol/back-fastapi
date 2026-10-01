import orjson
from fastapi import APIRouter, Response
from app.core.timing import timed
from app.domains.map import services
from app.domains.map.entities import Points
from app.domains.map.schemas import AreaSearch, FeatureCollection

router = APIRouter(tags=["map"])


@router.post("/searchSitesByArea", response_model=FeatureCollection)
def search_sites_by_area(search: AreaSearch):
    return _geojson(services.sites_in_area(search.bounds, with_details=False))


@router.post("/searchSitesByAreaDetails", response_model=FeatureCollection)
def search_sites_by_area_details(search: AreaSearch):
    return _geojson(services.sites_in_area(search.bounds, with_details=True))


@router.post("/searchSurveysByArea", response_model=FeatureCollection)
def search_surveys_by_area(search: AreaSearch):
    return _geojson(services.surveys_in_area(search.bounds, with_details=False))


@router.post("/searchSurveysByAreaDetails", response_model=FeatureCollection)
def search_surveys_by_area_details(search: AreaSearch):
    return _geojson(services.surveys_in_area(search.bounds, with_details=True))


def _geojson(points: Points) -> Response:
    with timed("geojson"):
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [row[0], row[1]]},
                "properties": dict(zip(points.property_names, row[2:])),
            }
            for row in points.rows
        ]
        content = orjson.dumps({"type": "FeatureCollection", "features": features})

    return Response(content, media_type="application/json")
