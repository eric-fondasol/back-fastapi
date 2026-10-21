# Le métier des enquêtes enregistrées : création (version 1), nouvelle version, écrasement de la
# dernière version, renommage, lecture et recherche. Repris des handlers du back Symfony.
# Chaque écriture se fait dans une transaction, enquête verrouillée (FOR UPDATE).

import uuid
from datetime import UTC, datetime

from app.core.errors import NotFound
from app.core.profile import Profile
from app.database.connection import refonte_transaction
from app.domains.investigations import entities, queries
from app.domains.investigations.entities import Author, Investigation, Summary, Version


# Les versions sont datées à la seconde (timestamp(0)) : on tronque avant, pour renvoyer ce qui est stocké.
def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


# L'auteur garde son nom affiché, ou à défaut son adresse.
def _author(profile: Profile) -> Author:
    return Author(profile.id, profile.display_name or profile.email)


def of_project(project_ref: str) -> list[tuple[Investigation, list[Version]]]:
    with refonte_transaction() as connection:
        investigations = queries.of_project(connection, project_ref)
        histories = queries.histories(connection, [investigation.uuid for investigation in investigations])

    return [(investigation, histories[investigation.uuid]) for investigation in investigations]


# Renvoie l'enquête, la version demandée (la dernière par défaut, avec son contenu) et le numéro
# de la dernière version.
def read(page_uuid: str, number: int | None = None) -> tuple[Investigation, Version, int]:
    with refonte_transaction() as connection:
        investigation = _existing(connection, page_uuid)
        latest = queries.latest_version(connection, page_uuid)

        if number is None:
            if latest is None:
                raise NotFound(f"Version d'enquete introuvable : {page_uuid}")
            return investigation, latest, latest.number

        found = queries.version(connection, page_uuid, number)

        if found is None:
            raise NotFound(f"Version d'enquete introuvable : {page_uuid} V{number}")

        return investigation, found, latest.number if latest else found.number


def create(profile: Profile, project_ref: str, name: str | None, data: str, comment: str | None) -> tuple[Investigation, Version]:
    data = entities.content(data)
    project_ref = entities.project_ref(project_ref)
    name = entities.name(name)
    comment = entities.comment(comment)
    page_uuid, now = str(uuid.uuid4()), _now()

    with refonte_transaction() as connection:
        queries.create(connection, page_uuid, data, profile.email, profile.display_name, project_ref, name, now)
        page_id = queries.lock(connection, page_uuid)
        version = queries.append_version(connection, page_id, data, comment, _author(profile), now)
        return _existing(connection, page_uuid), version


def add_version(profile: Profile, page_uuid: str, data: str, comment: str | None) -> tuple[Investigation, Version]:
    data, comment, now = entities.content(data), entities.comment(comment), _now()

    with refonte_transaction() as connection:
        page_id = queries.lock(connection, page_uuid)
        version = queries.append_version(connection, page_id, data, comment, _author(profile), now)
        queries.replace_content(connection, page_id, data, now)
        return _existing(connection, page_uuid), version


# Écraser une version : seulement la dernière (409 sinon) ; une version qui n'existe pas : 404.
def revise_version(profile: Profile, page_uuid: str, number: int, data: str, comment: str | None) -> tuple[Investigation, Version]:
    data, comment, now = entities.content(data), entities.comment(comment), _now()

    with refonte_transaction() as connection:
        page_id = queries.lock(connection, page_uuid)
        latest = queries.latest_number(connection, page_id)

        if latest == 0 or number > latest:
            raise NotFound(f"Version d'enquete introuvable : {page_uuid} V{number}")

        entities.assert_revisable(number, latest)
        version = queries.revise_version(connection, page_id, number, data, comment, _author(profile), now)
        queries.replace_content(connection, page_id, data, now)
        return _existing(connection, page_uuid), version


# Le nom vaut pour toutes les versions de l'enquête.
def rename(page_uuid: str, name: str | None) -> Investigation:
    name = entities.name(name)

    with refonte_transaction() as connection:
        page_id = queries.lock(connection, page_uuid)
        queries.rename(connection, page_id, name, _now())
        return _existing(connection, page_uuid)


def search(query: str | None, limit: int) -> list[Summary]:
    with refonte_transaction() as connection:
        return queries.search(connection, query, limit)


def _existing(connection, page_uuid: str) -> Investigation:
    found = queries.find(connection, page_uuid)

    if found is None:
        raise NotFound(f"Enquete introuvable : {page_uuid}")

    return found
