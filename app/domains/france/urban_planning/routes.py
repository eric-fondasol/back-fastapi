# Routes de l'urbanisme en France : /fr/urban-planning/…, lues sur l'API Solscore v2.
# Protégées par le jeton (le routeur France est branché avec dependencies=protected dans main.py).

from fastapi import APIRouter

from app.domains.france.relay import relayed
from app.domains.france.schemas import BufferSearch
from app.domains.france.urban_planning import sources

router = APIRouter(prefix="/urban-planning", tags=["France - Urban planning"])


# Fichiers des documents d'urbanisme (PLU, PLUi, carte communale…) qui couvrent le lieu (/fr/plu) :
# { mode_recherche, plu_documents: [{ id, name, doc_name, doc_title, url }] }. Pas encore appelée
# par le front (18/11/2026) : affichage à définir.
@router.post("/plu")
def urban_plans(search: BufferSearch) -> dict:
    return relayed(lambda: sources.urban_plans(search.body()))
