# Le SQL du socle : paramétrage, annuaire des agences, statistiques, zones à accès restreint,
# images d'attente. Repris des dépôts Doctrine du contexte Socle du back Symfony.

from datetime import datetime

from sqlalchemy import Connection, bindparam, text

from app.domains.socle.entities import AccessLimitedZone, AddressSearchTracing, Agency, Setting, WaitingImage


# Le paramétrage est historisé : la ligne la plus récente fait foi.
def current_setting(connection: Connection) -> Setting | None:
    row = connection.execute(
        text("SELECT email, message, url_manuel_utilisateur, horodatage FROM parametrages ORDER BY horodatage DESC NULLS LAST LIMIT 1")
    ).mappings().first()

    if row is None:
        return None

    return Setting(row["email"] or "", row["message"] or "", row["url_manuel_utilisateur"] or "", row["horodatage"])


def access_limited_zones(connection: Connection) -> list[AccessLimitedZone]:
    rows = connection.execute(
        text("SELECT id, description, latitude, longitude, zone_km FROM access_limited_zones ORDER BY id ASC")
    ).mappings()
    return [AccessLimitedZone(row["id"], row["description"], row["latitude"], row["longitude"], row["zone_km"]) for row in rows]


# Agence de l'agent, d'après son adresse (table email_services, sans tenir compte de la casse).
def service_code_of(connection: Connection, email: str) -> str | None:
    code = connection.execute(
        text("SELECT service_code FROM email_services WHERE LOWER(id) = LOWER(:email) LIMIT 1"), {"email": email}
    ).scalar()
    return code or None


def agency(connection: Connection, code: str | None) -> Agency | None:
    if not code:
        return None

    row = connection.execute(text("SELECT id, libelle, full_access FROM services WHERE id = :code"), {"code": code}).mappings().first()
    return _agency(row) if row else None


def codes_covering_department(connection: Connection, department: str) -> list[str]:
    return [
        str(code)
        for code in connection.execute(
            text("SELECT service FROM service_departments WHERE department = :department"), {"department": department}
        ).scalars()
    ]


# Agences principales d'un département (departments.code_service, codes séparés par « | »),
# dans l'ordre de cette liste.
def main_agencies_of_department(connection: Connection, department: str) -> list[Agency]:
    codes = connection.execute(text("SELECT code_service FROM departments WHERE id = :department"), {"department": department}).scalar()
    code_list = [code for code in (codes or "").split("|") if code]

    if not code_list:
        return []

    statement = text("SELECT id, libelle, full_access FROM services WHERE id IN :codes").bindparams(bindparam("codes", expanding=True))
    by_code = {row["id"]: _agency(row) for row in connection.execute(statement, {"codes": code_list}).mappings()}
    return [by_code[code] for code in code_list if code in by_code]


def add_address_search_tracing(connection: Connection, tracing: AddressSearchTracing) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO address_search_tracings
                (user_service_code, user_service_name, research_department_code, research_service_code,
                 research_service_name, is_authorized, longitude, latitude, horodatage)
            VALUES (:agency_code, :agency_label, :department_code, :covering_codes, :covering_labels,
                    :authorized, :longitude, :latitude, :recorded_at)
            RETURNING id
            """
        ),
        {
            "agency_code": tracing.agency_code,
            "agency_label": tracing.agency_label,
            "department_code": tracing.department_code,
            "covering_codes": tracing.covering_codes,
            "covering_labels": tracing.covering_labels,
            "authorized": tracing.authorized,
            "longitude": tracing.longitude,
            "latitude": tracing.latitude,
            "recorded_at": tracing.recorded_at,
        },
    ).scalar_one()


def add_visit(connection: Connection, label: str, at: datetime, service_code: str | None, email: str, tracing_id: int | None) -> None:
    connection.execute(
        text(
            "INSERT INTO statistique_visites (libelle, horodatage, service_code, user_email, address_search_tracing_id) "
            "VALUES (:label, :at, :service_code, :email, :tracing_id)"
        ),
        {"label": label, "at": at, "service_code": service_code, "email": email, "tracing_id": tracing_id},
    )


def waiting_images(connection: Connection) -> list[WaitingImage]:
    return [_image(row) for row in connection.execute(text("SELECT id, path, active FROM waiting_images ORDER BY id ASC")).mappings()]


def waiting_image(connection: Connection, image_id: int) -> WaitingImage | None:
    row = connection.execute(text("SELECT id, path, active FROM waiting_images WHERE id = :id"), {"id": image_id}).mappings().first()
    return _image(row) if row else None


def random_active_waiting_image(connection: Connection) -> WaitingImage | None:
    row = connection.execute(text("SELECT id, path, active FROM waiting_images WHERE active = true ORDER BY random() LIMIT 1")).mappings().first()
    return _image(row) if row else None


def add_waiting_image(connection: Connection, path: str) -> WaitingImage:
    row = connection.execute(
        text("INSERT INTO waiting_images (path, active) VALUES (:path, true) RETURNING id, path, active"), {"path": path}
    ).mappings().one()
    return _image(row)


def set_waiting_image_active(connection: Connection, image_id: int, active: bool) -> None:
    connection.execute(text("UPDATE waiting_images SET active = :active WHERE id = :id"), {"active": active, "id": image_id})


def remove_waiting_image(connection: Connection, image_id: int) -> None:
    connection.execute(text("DELETE FROM waiting_images WHERE id = :id"), {"id": image_id})


def _agency(row) -> Agency:
    return Agency(str(row["id"]), row["libelle"] or "", bool(row["full_access"]))


def _image(row) -> WaitingImage:
    return WaitingImage(row["id"], row["path"], row["active"])
