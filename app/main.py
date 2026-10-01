from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from app.core import health
from app.core.audit import audit
from app.core.auth import current_user, dev_token
from app.core.config import config
from app.domains.canada.routes import router as canada_router
from app.domains.france.routes import router as france_router
from app.domains.luxembourg.routes import router as luxembourg_router
from app.domains.map.routes import router as map_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    dev_token()
    yield


app = FastAPI(title="Solscore", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
app.middleware("http")(audit)

protected = [Depends(current_user)]

app.include_router(health.router)
app.include_router(map_router, dependencies=protected)
app.include_router(france_router, dependencies=protected)
app.include_router(canada_router, dependencies=protected)
app.include_router(luxembourg_router, dependencies=protected)


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse(url="/docs")
