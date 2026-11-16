# Routes du domaine map, à la racine pour garder le contrat actuel du front.
# Protégées par le jeton (dependencies=protected dans main.py).
# Les sites et sondages viennent de l'API Solscore v2 (sources.py), plus de la base d'apisolscore.

from collections.abc import Callable

import orjson
from fastapi import APIRouter, HTTPException, Response

from app.core.logger import logger
from app.core.timing import timed
from app.domains.map import services
from app.domains.map.schemas import AreaSearch, FeatureCollection
from app.domains.map.sources import SolscoreApiUnavailable

router = APIRouter(tags=["map"])


# FastAPI valide le corps avec AreaSearch avant d'appeler la fonction (422 si invalide).
# response_model ne sert qu'à décrire la réponse dans /docs : la Response renvoyée n'est pas revalidée.
@router.post("/searchSitesByArea", response_model=FeatureCollection)
def search_sites_by_area(search: AreaSearch):
    return _geojson(lambda: services.sites_in_area(search.bounds, with_details=False, filters=search.filters))


@router.post("/searchSitesByAreaDetails", response_model=FeatureCollection)
def search_sites_by_area_details(search: AreaSearch):
    return _geojson(lambda: services.sites_in_area(search.bounds, with_details=True, filters=search.filters))


@router.post("/searchSurveysByArea", response_model=FeatureCollection)
def search_surveys_by_area(search: AreaSearch):
    return _geojson(lambda: services.surveys_in_area(search.bounds, with_details=False, filters=search.filters))


@router.post("/searchSurveysByAreaDetails", response_model=FeatureCollection)
def search_surveys_by_area_details(search: AreaSearch):
    return _geojson(lambda: services.surveys_in_area(search.bounds, with_details=True, filters=search.filters))


def _geojson(features: Callable[[], list[dict]]) -> Response:
    try:
        points = features()
    except SolscoreApiUnavailable as error:
        logger.error("API Solscore injoignable pour la carte : %s", error)
        # 502 : c'est l'API Solscore qui est en défaut, pas la demande.
        raise HTTPException(status_code=502, detail="API Solscore injoignable") from error

    # Durée enregistrée sous « geojson » dans l'audit. orjson sérialise beaucoup plus vite que le
    # JSON standard de FastAPI ; Response directe : FastAPI n'a pas à reconvertir ni revalider.
    with timed("geojson"):
        content = orjson.dumps({"type": "FeatureCollection", "features": points})
    return Response(content, media_type="application/json")
