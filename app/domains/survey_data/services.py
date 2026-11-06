# Logique du domaine survey_data : lecture des listes, lecture et remplacement des niveaux d'un site.

from typing import Any

from app.core.errors import NotFound
from app.core.profile import Profile
from app.database.connection import refonte_transaction
from app.domains.survey_data import queries
from app.domains.survey_data.entities import (
    PenetrometerMachineType,
    Referentiel,
    SiteReferenceLevels,
    Standard,
    checked_structures,
    ground_elevation_from_json,
    structures_from_json,
)


def referentiels() -> list[Referentiel]:
    with refonte_transaction() as connection:
        return queries.referentiels(connection)


def standards() -> list[Standard]:
    with refonte_transaction() as connection:
        return queries.standards(connection)


def penetrometer_machine_types() -> list[PenetrometerMachineType]:
    with refonte_transaction() as connection:
        return queries.penetrometer_machine_types(connection)


def site_reference_levels(site_id: str) -> SiteReferenceLevels:
    with refonte_transaction() as connection:
        return _site_levels(connection, site_id)


# Forme du corps vérifiée avant toute lecture (400), règles métier ensuite (422), site inconnu : 404.
# Une cote du terrain naturel différente devient l'altitude du site, tracée dans l'historique.
def replace_site_reference_levels(site_id: str, payload: dict[str, Any], author: Profile) -> SiteReferenceLevels:
    structures = structures_from_json(payload)
    ground_elevation = ground_elevation_from_json(payload)
    with refonte_transaction() as connection:
        current = _site_levels(connection, site_id)
        standard_ids = {standard.id for standard in queries.standards(connection)}
        referentiel_codes = {referentiel.code for referentiel in queries.referentiels(connection)}
        queries.replace_site_structures(connection, site_id, checked_structures(structures, standard_ids, referentiel_codes))
        if ground_elevation.provided and ground_elevation.value != current.ground_elevation:
            queries.record_site_position(connection, site_id, author.id, author.email)
            queries.update_site_altitude(connection, site_id, ground_elevation.value)
        return _site_levels(connection, site_id)


def _site_levels(connection, site_id: str) -> SiteReferenceLevels:
    found, altitude = queries.site_altitude(connection, site_id)
    if not found:
        raise NotFound(f"Site introuvable : {site_id}")
    return SiteReferenceLevels(site_id=site_id, ground_elevation=altitude, structures=queries.site_structures(connection, site_id))
