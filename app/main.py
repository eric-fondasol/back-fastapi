from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from app.core import health, warmup
from app.core.audit import audit
from app.core.auth import current_user, dev_token
from app.core.config import config
from app.core.errors import DomainError, domain_error_response
from app.domains.canada.routes import router as canada_router
from app.domains.france.routes import router as france_router
from app.domains.luxembourg.routes import router as luxembourg_router
from app.domains.desk_study.routes import router as desk_study_router
from app.domains.investigations.routes import router as investigations_router
from app.domains.map.routes import router as map_router
from app.domains.profile.routes import router as profile_router
from app.domains.projects.routes import router as projects_router
from app.domains.reports.routes import router as reports_router
from app.domains.socle.routes import router as socle_router
from app.domains.survey_imports.routes import router as survey_imports_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Refuse de démarrer si AUTH_DEV_TOKEN est défini hors de APP_ENV=dev ou trop court.
    dev_token()
    # Charge à l'avance les clés Azure et ouvre les connexions à la base.
    warmup.warm_up()
    yield


app = FastAPI(title="Solscore", lifespan=lifespan)

# Navigateur : seules les origines de CORS_ORIGINS peuvent appeler l'API, avec ces méthodes et en-têtes.
# Ne protège pas des appels directs (curl, script) : c'est le rôle du jeton.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.allowed_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
# Une erreur métier levée par un service (core/errors.py) devient une réponse 400, 404, 409…
app.add_exception_handler(DomainError, domain_error_response)
# Trace chaque requête (qui, quoi, comment, quand) dans le journal du jour et la table audit_log.
app.middleware("http")(audit)

# Vérification du jeton (core/auth.py), exécutée avant chaque route des routeurs qui la reçoivent.
protected = [Depends(current_user)]

# /api/health reste publique : sonde d'état, sans donnée métier.
app.include_router(health.router)
# Tous les domaines métier sont protégés : une route ajoutée dans un thème l'est automatiquement.
app.include_router(map_router, dependencies=protected)
app.include_router(profile_router, dependencies=protected)
app.include_router(projects_router, dependencies=protected)
app.include_router(survey_imports_router, dependencies=protected)
app.include_router(investigations_router, dependencies=protected)
app.include_router(socle_router, dependencies=protected)
app.include_router(reports_router, dependencies=protected)
app.include_router(desk_study_router, dependencies=protected)
app.include_router(france_router, dependencies=protected)
app.include_router(canada_router, dependencies=protected)
app.include_router(luxembourg_router, dependencies=protected)


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse(url="/docs")
