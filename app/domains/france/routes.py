from fastapi import APIRouter

from app.domains.france.environment.routes import router as environment_router
from app.domains.france.geology.routes import router as geology_router
from app.domains.france.hydrogeology.routes import router as hydrogeology_router
from app.domains.france.natural_hazards.routes import router as natural_hazards_router
from app.domains.france.urban_planning.routes import router as urban_planning_router
from app.domains.france.weather.routes import router as weather_router

router = APIRouter(prefix="/fr")

router.include_router(environment_router)
router.include_router(geology_router)
router.include_router(hydrogeology_router)
router.include_router(natural_hazards_router)
router.include_router(urban_planning_router)
router.include_router(weather_router)
