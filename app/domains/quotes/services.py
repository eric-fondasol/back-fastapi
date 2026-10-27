# Logique métier des devis : appelé par routes.py, appelle sources.py.

from app.domains.quotes import sources
from app.domains.quotes.entities import Quote


# Renvoie le devis portant ce numéro, ou None si NAV n'en connaît aucun.
def find_quote(number: str) -> Quote | None:
    rows = sources.quote_rows(number)
    return Quote.from_nav(rows[0]) if rows else None
