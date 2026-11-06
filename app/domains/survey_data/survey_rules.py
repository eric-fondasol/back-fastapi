# Règles métier des données d'un sondage, reprises du front (core/projects/domain/surveyData/) : le back
# refuse (422) ce que le front aurait refusé. Fonctions pures : une liste de messages, vide si tout va bien.

from datetime import date

from app.domains.survey_data.entities import level_completeness_errors, level_order_errors
from app.domains.survey_data.survey_entities import HYDRO_MODES, SurveyData

EM_MAX = 9999.99
PRESSURE_MAX = 99.99
DRY_WELL_DEPTH = 9999
PRESSURE_MEASURES = ("em", "pl", "pf", "p0", "plp0", "pfp0")


def _complete_columns(rows: list[dict[str, float | None]], keys: tuple[str, ...], section: str) -> list[str]:
    errors = []
    for key in keys:
        filled = sum(1 for row in rows if row[key] is not None)
        if 0 < filled < len(rows):
            errors.append(f"{section} : {key} saisi à {filled} profondeurs sur {len(rows)}, à saisir partout ou nulle part.")
    return errors


def lithology_errors(data: SurveyData) -> list[str]:
    errors = []
    previous_end = None
    for index, layer in enumerate(data.lithology, start=1):
        if layer.depth_start < 0:
            errors.append(f"Lithologie, couche {index} : début négatif.")
        if previous_end is not None and layer.depth_start != previous_end:
            errors.append(f"Lithologie, couche {index} : doit commencer à la fin de la couche précédente ({previous_end} m).")
        if layer.depth_end <= layer.depth_start:
            errors.append(f"Lithologie, couche {index} : la fin doit être plus profonde que le début.")
        if layer.description == "":
            errors.append(f"Lithologie, couche {index} : description obligatoire.")
        previous_end = layer.depth_end
    return errors


def pressure_errors(data: SurveyData) -> list[str]:
    errors = []
    depths = [test.depth for test in data.pressures]
    for test in data.pressures:
        label = f"Pressiomètre, {test.depth} m"
        values = test.measures()
        if test.depth <= 0:
            errors.append(f"{label} : profondeur strictement positive attendue.")
        if all(value is None for value in values.values()):
            errors.append(f"{label} : au moins une mesure attendue.")
        if depths.count(test.depth) > 1:
            errors.append(f"{label} : profondeur en double.")
        for key, value in values.items():
            limit = EM_MAX if key == "em" else PRESSURE_MAX
            if value is not None and not 0 < value <= limit:
                errors.append(f"{label} : {key} doit être compris entre 0 (exclu) et {limit}.")
        for lower, upper in (("pf", "pl"), ("pfp0", "pf"), ("plp0", "pl")):
            if values[lower] is not None and values[upper] is not None and values[lower] > values[upper]:
                errors.append(f"{label} : {lower} doit être inférieur ou égal à {upper}.")
    return errors + _complete_columns([test.measures() for test in data.pressures], PRESSURE_MEASURES, "Pressiomètre")


def penetrometer_errors(data: SurveyData, machine_type_ids: set[int]) -> list[str]:
    test = data.penetrometer
    if test is None:
        return []
    errors = [f"Pénétromètre : {name} doit être strictement positif." for name, value in test.machine.items() if value is not None and value <= 0]
    if test.machine_type_id is not None and test.machine_type_id not in machine_type_ids:
        errors.append(f"Pénétromètre : type de machine inconnu ({test.machine_type_id}).")
    previous = None
    depths = [reading.depth for reading in test.readings]
    for reading in test.readings:
        label = f"Pénétromètre, {reading.depth} m"
        if reading.depth <= 0:
            errors.append(f"{label} : profondeur strictement positive attendue.")
        elif previous is not None and reading.depth < previous:
            errors.append(f"{label} : profondeurs croissantes attendues.")
        if depths.count(reading.depth) > 1:
            errors.append(f"{label} : profondeur en double.")
        if reading.blow_count is not None and (reading.blow_count < 0 or not float(reading.blow_count).is_integer()):
            errors.append(f"{label} : nombre de coups entier attendu.")
        if reading.qd is not None and reading.qd <= 0:
            errors.append(f"{label} : Qd strictement positif attendu.")
        if reading.blow_count is None and reading.qd is None:
            errors.append(f"{label} : nombre de coups ou Qd attendu.")
        previous = reading.depth
    rows = [{"blowCount": reading.blow_count, "qd": reading.qd} for reading in test.readings]
    return errors + _complete_columns(rows, ("blowCount", "qd"), "Pénétromètre")


def water_level_errors(data: SurveyData, referentiel_codes: set[str], today: date) -> list[str]:
    water = data.water_levels
    errors = []
    if water.measures and water.referentiel is None:
        errors.append("Suivi de nappe : référentiel obligatoire.")
    if water.referentiel is not None and water.referentiel not in referentiel_codes:
        errors.append(f"Suivi de nappe : référentiel inconnu ({water.referentiel}).")
    for measure in water.measures:
        label = f"Suivi de nappe, {measure.date.isoformat()}"
        if measure.date > today:
            errors.append(f"{label} : date dans le futur.")
        if measure.depth is None and measure.ref is None:
            errors.append(f"{label} : niveau en m/TA ou en m/réf. attendu.")
        if measure.depth == DRY_WELL_DEPTH and measure.ref is not None:
            errors.append(f"{label} : ouvrage sec (9999), pas de niveau en m/réf.")
    return errors


def reference_level_errors(data: SurveyData, standard_ids: set[int], referentiel_codes: set[str]) -> list[str]:
    reference = data.reference_levels
    errors = []
    if reference.has_level() and reference.standard_id is None:
        errors.append("Niveaux caractéristiques : norme obligatoire.")
    if reference.has_level() and reference.referentiel is None:
        errors.append("Niveaux caractéristiques : référentiel obligatoire.")
    if reference.standard_id is not None and reference.standard_id not in standard_ids:
        errors.append(f"Niveaux caractéristiques : norme inconnue ({reference.standard_id}).")
    if reference.referentiel is not None and reference.referentiel not in referentiel_codes:
        errors.append(f"Niveaux caractéristiques : référentiel inconnu ({reference.referentiel}).")
    messages = level_completeness_errors(reference.levels, required=False) + level_order_errors(reference.levels)
    return errors + [f"Niveaux caractéristiques : {message}" for message in messages]


def hydrodynamic_errors(data: SurveyData) -> list[str]:
    errors = []
    for index, test in enumerate(data.hydrodynamics.tests, start=1):
        label = f"Hydrodynamique, essai {index}"
        if test.mode not in HYDRO_MODES:
            errors.append(f"{label} : mode prélèvement ou injection attendu.")
        if test.top is not None and test.top < 0:
            errors.append(f"{label} : sommet de lanterne négatif.")
        if test.base is None:
            errors.append(f"{label} : base de lanterne obligatoire.")
        elif test.top is not None and test.base <= test.top:
            errors.append(f"{label} : la base de la lanterne doit être plus profonde que son sommet.")
        if test.permeability is None or test.permeability <= 0:
            errors.append(f"{label} : perméabilité strictement positive obligatoire.")
        for name, value in (("transmissivité", test.transmissivity), ("coefficient d'emmagasinement", test.storage)):
            if value is not None and value <= 0:
                errors.append(f"{label} : {name} strictement positif attendu.")
    return errors


def survey_data_errors(
    data: SurveyData, standard_ids: set[int], referentiel_codes: set[str], machine_type_ids: set[int], today: date
) -> list[str]:
    return (
        lithology_errors(data)
        + pressure_errors(data)
        + penetrometer_errors(data, machine_type_ids)
        + water_level_errors(data, referentiel_codes, today)
        + reference_level_errors(data, standard_ids, referentiel_codes)
        + hydrodynamic_errors(data)
    )
