# Route du catalogue des couches : GET /layer-catalog. Contrat attendu par le front (ADR-0043,
# docs/features/map.md). Protégée par le jeton (branchée avec dependencies=protected dans main.py).

from typing import Any

from fastapi import APIRouter

from app.domains.layer_catalog import services

router = APIRouter(tags=["Layer catalog"])


# { "categories": [{ "code": "geologie", "label": { "fr": "Géologie", "en": "Geology" } }],
#   "layers": [{ "code": "fr-geologie", "category": "geologie", "country": "fr", "label": {…}, "kind": "wms", … }] }
@router.get("/layer-catalog")
def layer_catalog() -> dict[str, Any]:
    return services.catalog()
