# Route des devis : /quotes/{numéro}, pour la recherche par n° de devis de la carte.
# Protégée par le jeton (branchée avec dependencies=protected dans main.py).

from fastapi import APIRouter, HTTPException

from app.core.logger import logger
from app.domains.quotes import services
from app.domains.quotes.schemas import QuoteAnswer, QuotePosition, quote_number
from app.domains.quotes.sources import QuotesUnavailable

router = APIRouter(prefix="/quotes", tags=["Quotes"])


# Devis lu dans NAV : son affaire et son adresse de livraison. 422 numéro invalide, 404 inconnu.
@router.get("/{number}", response_model=QuoteAnswer)
def find_quote(number: str) -> QuoteAnswer:
    checked = quote_number(number)
    if checked is None:
        raise HTTPException(status_code=422, detail="Numéro de devis invalide")
    try:
        quote = services.find_quote(checked)
    except QuotesUnavailable as error:
        logger.error("Navision injoignable pour le devis %s : %s", checked, error)
        # 502 : c'est Navision qui est en défaut, pas la demande.
        raise HTTPException(status_code=502, detail="Navision injoignable") from error
    if quote is None:
        raise HTTPException(status_code=404, detail=f"Devis {checked} introuvable")

    position = None if quote.longitude is None or quote.latitude is None else QuotePosition(longitude=quote.longitude, latitude=quote.latitude)
    return QuoteAnswer(
        number=quote.number,
        project_number=quote.project_number,
        description=quote.description,
        address=quote.address,
        post_code=quote.post_code,
        city=quote.city,
        country_code=quote.country_code,
        position=position,
    )
