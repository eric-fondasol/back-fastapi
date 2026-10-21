# Regroupe les thèmes du Canada sous le préfixe /ca. Branché et protégé par le jeton dans main.py.
# Ajouter un thème : importer son routeur ici et l'inclure ci-dessous.

from fastapi import APIRouter

from app.domains.canada.contamination.routes import router as contamination_router
from app.domains.canada.environment.routes import router as environment_router
from app.domains.canada.geology.routes import router as geology_router
from app.domains.canada.infrastructure.routes import router as infrastructure_router
from app.domains.canada.land_registry.routes import router as land_registry_router

router = APIRouter(prefix="/ca")

# Chaque thème ajoute son propre préfixe : /ca/contamination/…, /ca/geology/…
router.include_router(contamination_router)
router.include_router(environment_router)
router.include_router(geology_router)
router.include_router(infrastructure_router)
router.include_router(land_registry_router)
