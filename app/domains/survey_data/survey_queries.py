# SQL des données saisies d'un sondage, sur la base métier (refonte). Une fonction par requête.
# Chaque section enregistrée remplace les lignes du sondage dans sa table (pas de fusion ligne à ligne).

from dataclasses import dataclass

from sqlalchemy import Connection, text

from app.domains.survey_data.entities import LEVEL_IDS, Level
from app.domains.survey_data.survey_entities import (
    MACHINE_FIELDS,
    HydrodynamicTest,
    Hydrodynamics,
    LithologyLayer,
    PenetrometerReading,
    PenetrometerTest,
    PressureTest,
    SurveyData,
    SurveyReferenceLevels,
    WaterLevelMeasure,
    WaterLevels,
)

MACHINE_COLUMNS = {
    "hammerDropHeight": "hammer_drop_height",
    "hammerMass": "hammer_mass",
    "anvilMass": "anvil_mass",
    "rodMass": "rod_mass",
    "tipSection": "tip_section",
}
LEVEL_COLUMNS = [f"{level_id}_{column}" for level_id in LEVEL_IDS for column in ("depth", "ref")]


@dataclass(frozen=True)
class SurveyRow:
    id: str
    site_id: str
    altitude: float | None


def find_survey(connection: Connection, survey_id: str) -> SurveyRow | None:
    row = connection.execute(text("SELECT id, site_id, altitude FROM surveys WHERE id = :id"), {"id": survey_id}).first()
    return None if row is None else SurveyRow(id=row.id, site_id=row.site_id, altitude=row.altitude)


def read_survey_data(connection: Connection, survey_id: str) -> SurveyData:
    parameters = {"id": survey_id}
    lithology = [
        LithologyLayer(depth_start=row.depth_start, depth_end=row.depth_end, description=row.description_fr or "")
        for row in connection.execute(
            text(
                "SELECT depth_start, depth_end, description_fr FROM lithologies WHERE survey_id = :id "
                "AND depth_start IS NOT NULL AND depth_end IS NOT NULL ORDER BY depth_start, depth_end"
            ),
            parameters,
        )
    ]
    pressures = [
        PressureTest(depth=row.depth, em=row.em, pl=row.pl, pf=row.pf, p0=row.p0, plp0=row.plp0, pfp0=row.pfp0)
        for row in connection.execute(text("SELECT depth, em, pl, pf, p0, plp0, pfp0 FROM pressures WHERE survey_id = :id ORDER BY depth"), parameters)
    ]
    test = connection.execute(
        text(
            f"SELECT id, machine_type_id, {', '.join(MACHINE_COLUMNS.values())} FROM penetrometer_tests "
            "WHERE survey_id = :id ORDER BY created_at, id LIMIT 1"
        ),
        parameters,
    ).mappings().first()
    penetrometer = None
    if test is not None:
        readings = [
            PenetrometerReading(depth=row.depth, blow_count=row.blow_count, qd=row.qd)
            for row in connection.execute(text("SELECT depth, blow_count, qd FROM penetrometer_readings WHERE test_id = :test ORDER BY depth"), {"test": test["id"]})
        ]
        penetrometer = PenetrometerTest(
            machine_type_id=test["machine_type_id"], machine={name: test[column] for name, column in MACHINE_COLUMNS.items()}, readings=readings
        )
    water_rows = connection.execute(
        text(
            "SELECT (measured_at AT TIME ZONE 'UTC')::date AS day, depth_m, level_ref, referentiel FROM water_levels_manual "
            "WHERE survey_id = :id AND measured_at IS NOT NULL ORDER BY measured_at"
        ),
        parameters,
    ).all()
    reference = connection.execute(
        text(f"SELECT standard_id, referentiel, {', '.join(LEVEL_COLUMNS)} FROM gw_reference_levels WHERE survey_id = :id ORDER BY id LIMIT 1"),
        parameters,
    ).mappings().first()
    hydro_tests = [
        HydrodynamicTest(
            mode=row.mode,
            long_duration_pumping=row.long_duration_pumping,
            top=row.screen_top,
            base=row.screen_base,
            permeability=row.permeability,
            transmissivity=row.transmissivity,
            storage=row.storage_coefficient,
            facies=row.facies,
            notes=row.notes,
        )
        for row in connection.execute(
            text(
                "SELECT mode, long_duration_pumping, screen_top, screen_base, permeability, transmissivity, storage_coefficient, facies, notes "
                "FROM water_testing_parameters WHERE survey_id = :id ORDER BY position"
            ),
            parameters,
        )
    ]
    return SurveyData(
        lithology=lithology,
        pressures=pressures,
        penetrometer=penetrometer,
        water_levels=WaterLevels(
            referentiel=next((row.referentiel for row in water_rows if row.referentiel is not None), None),
            measures=[WaterLevelMeasure(date=row.day, depth=row.depth_m, ref=row.level_ref) for row in water_rows],
        ),
        reference_levels=SurveyReferenceLevels()
        if reference is None
        else SurveyReferenceLevels(
            standard_id=reference["standard_id"],
            referentiel=reference["referentiel"],
            levels={level_id: Level(depth=reference[f"{level_id}_depth"], ref=reference[f"{level_id}_ref"]) for level_id in LEVEL_IDS},
        ),
        hydrodynamics=Hydrodynamics(tests=hydro_tests),
    )


def replace_survey_data(connection: Connection, survey: SurveyRow, data: SurveyData, machine_type: str | None) -> None:
    parameters = {"id": survey.id}

    connection.execute(text("DELETE FROM lithologies WHERE survey_id = :id"), parameters)
    for layer in data.lithology:
        connection.execute(
            text(
                "INSERT INTO lithologies (id, survey_id, depth_start, depth_end, description_fr) "
                "VALUES (gen_random_uuid()::text, :id, :start, :end, :description)"
            ),
            parameters | {"start": layer.depth_start, "end": layer.depth_end, "description": layer.description},
        )

    connection.execute(text("DELETE FROM pressures WHERE survey_id = :id"), parameters)
    for test in data.pressures:
        connection.execute(
            text(
                "INSERT INTO pressures (id, survey_id, depth, em, pl, pf, p0, plp0, pfp0) "
                "VALUES (gen_random_uuid()::text, :id, :depth, :em, :pl, :pf, :p0, :plp0, :pfp0)"
            ),
            parameters | test.to_json(),
        )

    connection.execute(text("DELETE FROM penetrometer_tests WHERE survey_id = :id"), parameters)
    if data.penetrometer is not None and not data.penetrometer.is_empty():
        machine = {MACHINE_COLUMNS[name]: data.penetrometer.machine[name] for name in MACHINE_FIELDS}
        test_id = connection.execute(
            text(
                f"INSERT INTO penetrometer_tests (survey_id, type, machine_type_id, {', '.join(machine)}) "
                f"VALUES (:id, :type, :machine_type_id, {', '.join(':' + column for column in machine)}) RETURNING id"
            ),
            parameters | {"type": machine_type, "machine_type_id": data.penetrometer.machine_type_id} | machine,
        ).scalar()
        for reading in data.penetrometer.readings:
            connection.execute(
                text("INSERT INTO penetrometer_readings (test_id, depth, blow_count, qd) VALUES (:test, :depth, :blows, :qd)"),
                {"test": test_id, "depth": reading.depth, "blows": reading.blow_count, "qd": reading.qd},
            )

    connection.execute(text("DELETE FROM water_levels_manual WHERE survey_id = :id"), parameters)
    for measure in data.water_levels.measures:
        connection.execute(
            text(
                "INSERT INTO water_levels_manual (survey_id, measured_at, depth_m, level_ref, referentiel) "
                "VALUES (:id, CAST(:day AS date)::timestamp AT TIME ZONE 'UTC', :depth, :ref, :referentiel)"
            ),
            parameters | {"day": measure.date.isoformat(), "depth": measure.depth, "ref": measure.ref, "referentiel": data.water_levels.referentiel},
        )

    connection.execute(text("DELETE FROM gw_reference_levels WHERE survey_id = :id"), parameters)
    reference = data.reference_levels
    if not reference.is_empty():
        levels = {f"{level_id}_{column}": getattr(reference.levels.get(level_id, Level()), column) for level_id in LEVEL_IDS for column in ("depth", "ref")}
        connection.execute(
            text(
                f"INSERT INTO gw_reference_levels (survey_id, site_id, standard_id, referentiel, {', '.join(LEVEL_COLUMNS)}) "
                f"VALUES (:id, :site_id, :standard_id, :referentiel, {', '.join(':' + column for column in LEVEL_COLUMNS)})"
            ),
            parameters | {"site_id": survey.site_id, "standard_id": reference.standard_id, "referentiel": reference.referentiel} | levels,
        )

    connection.execute(text("DELETE FROM water_testing_parameters WHERE survey_id = :id"), parameters)
    for position, test in enumerate(data.hydrodynamics.tests):
        connection.execute(
            text(
                "INSERT INTO water_testing_parameters (survey_id, position, mode, long_duration_pumping, screen_top, screen_base, "
                "permeability, transmissivity, storage_coefficient, facies, notes) VALUES (:id, :position, :mode, :longDurationPumping, "
                ":top, :base, :permeability, :transmissivity, :storage, :facies, :notes)"
            ),
            parameters | {"position": position} | test.to_json(),
        )

    last_layer_end = data.lithology[-1].depth_end if data.lithology else None
    connection.execute(
        text(
            "UPDATE surveys SET has_lithology = :lithology, has_pressuremeter = :pressures, has_penetrometer = :penetrometer, "
            "has_water_levels = :water, is_water_testing = :water_testing, depth_max = coalesce(:depth_max, depth_max) WHERE id = :id"
        ),
        parameters
        | {
            "lithology": bool(data.lithology),
            "pressures": bool(data.pressures),
            "penetrometer": data.penetrometer is not None and bool(data.penetrometer.readings),
            "water": bool(data.water_levels.measures),
            "water_testing": bool(data.hydrodynamics.tests),
            "depth_max": last_layer_end,
        },
    )


# Historique de géolocalisation (schéma v4), même trace que l'onglet Géolocalisation : position et altitude du
# sondage juste avant la modification, avec l'agent.
def record_survey_position(connection: Connection, survey_id: str, author_id: str, author_email: str) -> None:
    connection.execute(
        text(
            "INSERT INTO geolocation_correction_history (site_id, survey_id, project_id, longitude, latitude, altitude, id_user, user_email) "
            "SELECT sv.site_id, sv.id, s.project_id, ST_X(sv.geometry), ST_Y(sv.geometry), sv.altitude, :author_id, :author_email "
            "FROM surveys sv JOIN sites s ON s.id = sv.site_id WHERE sv.id = :id"
        ),
        {"id": survey_id, "author_id": author_id, "author_email": author_email},
    )


def update_survey_altitude(connection: Connection, survey_id: str, altitude: float | None) -> None:
    connection.execute(text("UPDATE surveys SET altitude = :altitude WHERE id = :id"), {"id": survey_id, "altitude": altitude})


def machine_types(connection: Connection) -> dict[int, str]:
    return {row.id: row.type for row in connection.execute(text("SELECT id, type FROM penetrometer_machine_types"))}
