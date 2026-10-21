# Routes du domaine map, à la racine pour garder le contrat actuel du front.
# Protégées par le jeton (dependencies=protected dans main.py).

import orjson
from fastapi import APIRouter, Response
from app.core.timing import timed
from app.domains.map import services
from app.domains.map.entities import Points
from app.domains.map.schemas import AreaSearch, FeatureCollection

router = APIRouter(tags=["map"])


# FastAPI valide le corps avec AreaSearch avant d'appeler la fonction (422 si invalide).
# response_model ne sert qu'à décrire la réponse dans /docs : la Response renvoyée n'est pas revalidée.
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


# Convertit les points en GeoJSON (FeatureCollection de Points).
def _geojson(points: Points) -> Response:
    # Durée enregistrée sous « geojson » dans l'audit.
    with timed("geojson"):
        features = [
            {
                "type": "Feature",
                # Ordre GeoJSON : longitude puis latitude (les deux premières colonnes).
                "geometry": {"type": "Point", "coordinates": [row[0], row[1]]},
                # Les colonnes suivantes, associées à leur nom.
                "properties": dict(zip(points.property_names, row[2:])),
            }
            for row in points.rows
        ]
        # orjson sérialise beaucoup plus vite que le JSON standard de FastAPI.
        content = orjson.dumps({"type": "FeatureCollection", "features": features})

    # Response directe : FastAPI n'a pas à reconvertir ni revalider les données.
    return Response(content, media_type="application/json")
