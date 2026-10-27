# Contrat de l'API des devis : contrôle du numéro demandé, forme de la réponse (Pydantic).

import re

from pydantic import BaseModel

# Numéro de devis NAV : lettres, chiffres, points et tirets (« SQ.31GT.26.10.025 »). Ni apostrophe ni
# espace : rien ne peut sortir du filtre OData.
QUOTE_NUMBER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,39}$")


# Numéro tel que NAV l'enregistre (en majuscules, sans espaces autour), ou None s'il est invalide.
def quote_number(typed: str) -> str | None:
    number = typed.strip().upper()
    return number if QUOTE_NUMBER.fullmatch(number) else None


class QuotePosition(BaseModel):
    longitude: float
    latitude: float


class QuoteAnswer(BaseModel):
    number: str
    # Numéro de l'affaire Solscore (sans le « PR. » de NAV), None si le devis n'en a pas encore.
    project_number: str | None
    description: str
    address: str
    post_code: str
    city: str
    country_code: str
    # Adresse de livraison géolocalisée par NAV, None sinon.
    position: QuotePosition | None
