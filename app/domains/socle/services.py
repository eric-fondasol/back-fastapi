# Le métier du socle : paramétrage, statistiques de visite et de recherche d'adresse, zones à
# accès restreint, images d'attente. Repris des handlers du contexte Socle du back Symfony.

import uuid
from dataclasses import replace
from datetime import UTC, datetime

from app.core.errors import InvalidRequest
from app.database.connection import refonte_transaction
from app.domains.socle import entities, queries, sources
from app.domains.socle.entities import AccessLimitedZone, AddressSearchTracing, Setting, WaitingImage


def _now() -> datetime:
    return datetime.now(UTC)


def current_setting() -> Setting | None:
    with refonte_transaction() as connection:
        return queries.current_setting(connection)


def access_limited_zones() -> list[AccessLimitedZone]:
    with refonte_transaction() as connection:
        return queries.access_limited_zones(connection)


# Une visite est rattachée au service de l'agent, s'il est connu de l'annuaire.
def record_visit(label: str, email: str) -> tuple[str | None, datetime]:
    now = _now()

    with refonte_transaction() as connection:
        service_code = queries.service_code_of(connection, email)
        queries.add_visit(connection, label, now, service_code, email, None)

    return service_code, now


# Trace une recherche d'adresse : le département cherché, les agences qui le couvrent, et si
# l'agent y est habilité. Une visite pointant vers cette trace est enregistrée en même temps.
def record_address_search(department: str, label: str, longitude: float, latitude: float, email: str) -> AddressSearchTracing:
    now = _now()

    with refonte_transaction() as connection:
        agency_code = queries.service_code_of(connection, email)
        agency = queries.agency(connection, agency_code)
        covering = queries.main_agencies_of_department(connection, department)
        tracing = AddressSearchTracing(
            agency_code=agency_code,
            agency_label=agency.label if agency else None,
            department_code=department,
            covering_codes=entities.joined([covering_agency.code for covering_agency in covering]),
            covering_labels=entities.joined([covering_agency.label for covering_agency in covering]),
            authorized=entities.allows(agency, queries.codes_covering_department(connection, department)),
            longitude=longitude,
            latitude=latitude,
            recorded_at=now,
        )
        tracing = replace(tracing, id=queries.add_address_search_tracing(connection, tracing))
        queries.add_visit(connection, label, now, agency_code, email, tracing.id)
        return tracing


def waiting_images() -> list[WaitingImage]:
    with refonte_transaction() as connection:
        return queries.waiting_images(connection)


def random_waiting_image() -> WaitingImage | None:
    with refonte_transaction() as connection:
        return queries.random_active_waiting_image(connection)


# Seules les vraies images (JPEG, PNG, GIF, WebP, reconnues à leur contenu) sont acceptées.
def upload_waiting_image(original_name: str, content: bytes) -> WaitingImage:
    mime = entities.image_type(content)

    if mime is None:
        raise InvalidRequest("Seules les images sont acceptees.")

    name = entities.stored_name(str(uuid.uuid4()), original_name, mime)
    sources.store(name, content)

    with refonte_transaction() as connection:
        return queries.add_waiting_image(connection, name)


# Renvoie False si l'image n'existe pas : rien n'est créé.
def switch_waiting_image(image_id: int, active: bool) -> bool:
    with refonte_transaction() as connection:
        if queries.waiting_image(connection, image_id) is None:
            return False

        queries.set_waiting_image_active(connection, image_id, active)
        return True


def delete_waiting_image(image_id: int) -> bool:
    with refonte_transaction() as connection:
        image = queries.waiting_image(connection, image_id)

        if image is None:
            return False

        sources.delete(image.path)
        queries.remove_waiting_image(connection, image_id)
        return True
