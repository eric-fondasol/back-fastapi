# SQL du domaine survey_data, sur la base métier (refonte). Une fonction par requête.

from sqlalchemy import Connection, text

from app.domains.survey_data.entities import LEVEL_IDS, Level, PenetrometerMachineType, Referentiel, Standard, StructureLevels


def referentiels(connection: Connection) -> list[Referentiel]:
    rows = connection.execute(text("SELECT code, label_fr, label_en FROM referentiels ORDER BY position NULLS LAST, code"))
    return [Referentiel(code=row.code, label_fr=row.label_fr, label_en=row.label_en) for row in rows]


def standards(connection: Connection) -> list[Standard]:
    rows = connection.execute(text("SELECT id, code, label FROM standards ORDER BY position NULLS LAST, code"))
    return [Standard(id=row.id, code=row.code, label=row.label) for row in rows]


def penetrometer_machine_types(connection: Connection) -> list[PenetrometerMachineType]:
    rows = connection.execute(
        text(
            "SELECT id, type, hammer_mass, hammer_drop_height, rod_mass, anvil_mass, tip_mass, tip_section, penetration "
            "FROM penetrometer_machine_types ORDER BY type"
        )
    )
    return [
        PenetrometerMachineType(
            id=row.id,
            type=row.type,
            hammer_mass=row.hammer_mass,
            hammer_drop_height=row.hammer_drop_height,
            rod_mass=row.rod_mass,
            accessories_mass=row.anvil_mass,
            tip_mass=row.tip_mass,
            tip_section=row.tip_section,
            penetration=row.penetration,
        )
        for row in rows
    ]


# Altitude du site, ou None si le site n'existe pas (distingué par found).
def site_altitude(connection: Connection, site_id: str) -> tuple[bool, float | None]:
    row = connection.execute(text("SELECT altitude FROM sites WHERE id = :site_id"), {"site_id": site_id}).first()
    return (False, None) if row is None else (True, row.altitude)


def _level_columns() -> list[str]:
    return [f"{level_id}_{column}" for level_id in LEVEL_IDS for column in ("depth", "ref")]


# Niveaux saisis au site : lignes sans sondage. Triées par nom d'ouvrage (la table n'a pas d'ordre).
def site_structures(connection: Connection, site_id: str) -> list[StructureLevels]:
    rows = connection.execute(
        text(
            f"SELECT structure, standard_id, referentiel, {', '.join(_level_columns())} FROM gw_reference_levels "
            "WHERE site_id = :site_id AND survey_id IS NULL ORDER BY lower(coalesce(structure, '')), id"
        ),
        {"site_id": site_id},
    ).mappings()
    return [
        StructureLevels(
            structure=row["structure"] or "",
            standard_id=row["standard_id"],
            referentiel=row["referentiel"],
            levels={level_id: Level(depth=row[f"{level_id}_depth"], ref=row[f"{level_id}_ref"]) for level_id in LEVEL_IDS},
        )
        for row in rows
    ]


# Remplace tous les ouvrages du site ; les niveaux des sondages (survey_id renseigné) ne sont pas touchés.
def replace_site_structures(connection: Connection, site_id: str, structures: list[StructureLevels]) -> None:
    connection.execute(text("DELETE FROM gw_reference_levels WHERE site_id = :site_id AND survey_id IS NULL"), {"site_id": site_id})
    columns = _level_columns()
    for entry in structures:
        values = {f"{level_id}_{column}": getattr(entry.levels[level_id], column) for level_id in LEVEL_IDS for column in ("depth", "ref")}
        connection.execute(
            text(
                f"INSERT INTO gw_reference_levels (site_id, structure, standard_id, referentiel, {', '.join(columns)}) "
                f"VALUES (:site_id, :structure, :standard_id, :referentiel, {', '.join(':' + column for column in columns)})"
            ),
            {"site_id": site_id, "structure": entry.structure, "standard_id": entry.standard_id, "referentiel": entry.referentiel} | values,
        )


# Historique de géolocalisation (schéma v4) : position et altitude du site juste avant la modification,
# avec l'agent ; même trace que les corrections faites depuis l'onglet Géolocalisation.
def record_site_position(connection: Connection, site_id: str, author_id: str, author_email: str) -> None:
    connection.execute(
        text(
            "INSERT INTO geolocation_correction_history (site_id, project_id, longitude, latitude, altitude, id_user, user_email) "
            "SELECT id, project_id, ST_X(geometry), ST_Y(geometry), altitude, :author_id, :author_email FROM sites WHERE id = :site_id"
        ),
        {"site_id": site_id, "author_id": author_id, "author_email": author_email},
    )


def update_site_altitude(connection: Connection, site_id: str, altitude: float | None) -> None:
    connection.execute(text("UPDATE sites SET altitude = :altitude WHERE id = :site_id"), {"site_id": site_id, "altitude": altitude})
