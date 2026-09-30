from fastapi import APIRouter

from app.domains.canada.contamination.routes import router as contamination_router
from app.domains.canada.environment.routes import router as environment_router
from app.domains.canada.geology.routes import router as geology_router
from app.domains.canada.infrastructure.routes import router as infrastructure_router

router = APIRouter(prefix="/ca")

router.include_router(contamination_router)
router.include_router(environment_router)
router.include_router(geology_router)
router.include_router(infrastructure_router)
