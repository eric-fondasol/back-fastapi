# Regroupe les thèmes du Luxembourg sous le préfixe /lu. Branché et protégé par le jeton dans main.py.
# Ajouter un thème : importer son routeur ici et l'inclure ci-dessous.

from fastapi import APIRouter

from app.domains.luxembourg.geology.routes import router as geology_router

router = APIRouter(prefix="/lu")

# Le thème ajoute son propre préfixe : /lu/geology/…
router.include_router(geology_router)
