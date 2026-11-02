# Regroupe les thèmes du Luxembourg sous le préfixe /lu. Branché et protégé par le jeton dans main.py.
# Ajouter un thème : importer son routeur ici et l'inclure ci-dessous.

from fastapi import APIRouter

from app.domains.luxembourg.geology.routes import router as geology_router
from app.domains.luxembourg.land_registry.routes import router as land_registry_router

router = APIRouter(prefix="/lu")

# Chaque thème ajoute son propre préfixe : /lu/geology/…, /lu/land-registry/…
router.include_router(geology_router)
router.include_router(land_registry_router)
