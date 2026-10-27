# Données du service externe : les devis de Dynamics NAV (Navision), lus par son API OData V4
# (page FDS_API_Devis_RapportAutomatique, celle que l'ancien front interrogeait), en Basic Auth.

import httpx

from app.core.config import config

QUOTES_PAGE = "FDS_API_Devis_RapportAutomatique"
# Seuls les champs utiles à la carte : la page en publie près de 80 (client, montants, agence…).
FIELDS = (
    "No",
    "Job_No",
    "Job_Description",
    "Delivery_Address",
    "Delivery_Post_Code",
    "Delivery_City",
    "Delivery_Country_Region_Code",
    "Delivery_GPS_Longitude",
    "Delivery_GPS_Latitude",
)
# Au-delà de 10 s sans réponse, Navision est considéré comme injoignable.
TIMEOUT_SECONDS = 10.0

# Remplacé par les tests pour simuler Navision (httpx.MockTransport).
transport: httpx.BaseTransport | None = None


# Erreur propre au domaine, traduite en 502 par routes.py. Le service n'a pas à connaître httpx.
class QuotesUnavailable(Exception):
    pass


# Lignes de la page des devis portant ce numéro (une au plus en pratique), telles que NAV les renvoie.
def quote_rows(number: str) -> list[dict]:
    if not (config.nav_odata_base_uri and config.nav_username and config.nav_password):
        raise QuotesUnavailable("NAV_ODATA_BASE_URI, NAV_USERNAME ou NAV_PASSWORD absent de la configuration")

    # Le numéro ne contient ni apostrophe ni espace (schemas.py) : il se place tel quel dans le filtre.
    params = {"$filter": f"No eq '{number}'", "$select": ",".join(FIELDS)}
    try:
        with httpx.Client(
            auth=(config.nav_username, config.nav_password.get_secret_value()),
            timeout=TIMEOUT_SECONDS,
            transport=transport,
        ) as client:
            response = client.get(f"{config.nav_odata_base_uri.rstrip('/')}/{QUOTES_PAGE}", params=params)
            response.raise_for_status()
            body = response.json()
    # Erreur réseau, délai dépassé, identifiants refusés, ou réponse qui n'est pas du JSON (ValueError).
    except (httpx.HTTPError, ValueError) as error:
        raise QuotesUnavailable(str(error)) from error

    if not isinstance(body, dict) or not isinstance(body.get("value"), list):
        raise QuotesUnavailable(str(body)[:200])
    return body["value"]
