# Objets métier des devis, manipulés par services.py. Ce ne sont pas des modèles de tables.

from dataclasses import dataclass

# NAV préfixe le numéro d'affaire de « PR. » (« PR.31GT.26.0134 ») ; Solscore l'enregistre sans
# (« 31GT.26.0134 », vérifié le 27/10/2026 sur la table affaire avec numero_devis).
NAV_PROJECT_PREFIX = "PR."


# Devis tel que la carte l'utilise : son affaire et son adresse de livraison (le lieu de la mission).
@dataclass(frozen=True)
class Quote:
    number: str
    project_number: str | None
    description: str
    address: str
    post_code: str
    city: str
    country_code: str
    # Position GPS de l'adresse de livraison en WGS 84, None quand NAV n'en a pas (0, 0).
    longitude: float | None
    latitude: float | None

    @classmethod
    def from_nav(cls, row: dict) -> "Quote":
        longitude = _coordinate(row.get("Delivery_GPS_Longitude"), 180)
        latitude = _coordinate(row.get("Delivery_GPS_Latitude"), 90)
        located = longitude is not None and latitude is not None and (longitude, latitude) != (0, 0)
        return cls(
            number=str(row.get("No") or ""),
            project_number=_project_number(row.get("Job_No")),
            description=str(row.get("Job_Description") or ""),
            address=str(row.get("Delivery_Address") or ""),
            post_code=str(row.get("Delivery_Post_Code") or ""),
            city=str(row.get("Delivery_City") or ""),
            country_code=str(row.get("Delivery_Country_Region_Code") or ""),
            longitude=longitude if located else None,
            latitude=latitude if located else None,
        )


def _project_number(job_number: object) -> str | None:
    if not isinstance(job_number, str) or not job_number.strip():
        return None
    number = job_number.strip()
    return number[len(NAV_PROJECT_PREFIX) :] if number.startswith(NAV_PROJECT_PREFIX) else number


def _coordinate(value: object, limit: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or abs(value) > limit:
        return None
    return float(value)
