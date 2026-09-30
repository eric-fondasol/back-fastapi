from fastapi import APIRouter

from app.domains.luxembourg.geology.routes import router as geology_router

router = APIRouter(prefix="/lu")

router.include_router(geology_router)
