from datetime import date

import pytest

from app.core.errors import InvalidRequest
from app.domains.survey_data.survey_entities import survey_data_from_json
from app.domains.survey_data.survey_rules import survey_data_errors

TODAY = date(2026, 11, 6)


def errors(**payload):
    return survey_data_errors(survey_data_from_json(payload), {1, 2}, {"NGF", "LUREF"}, {7}, TODAY)


def test_an_empty_survey_is_valid():
    assert errors() == []


def test_lithology_layers_follow_each_other_and_have_a_description():
    assert errors(lithology=[{"depthStart": 0, "depthEnd": 1.2, "description": "Remblais"}, {"depthStart": 1.2, "depthEnd": 3, "description": "Sable"}]) == []
    assert errors(lithology=[{"depthStart": -1, "depthEnd": 1, "description": "A"}, {"depthStart": 2, "depthEnd": 1.5, "description": " "}]) == [
        "Lithologie, couche 1 : début négatif.",
        "Lithologie, couche 2 : doit commencer à la fin de la couche précédente (1.0 m).",
        "Lithologie, couche 2 : la fin doit être plus profonde que le début.",
        "Lithologie, couche 2 : description obligatoire.",
    ]


def test_pressure_rules_and_complete_columns():
    assert errors(pressures=[{"depth": 1, "pl": 1.5, "p0": 0.1, "plp0": 1.4}, {"depth": 2, "pl": 2, "p0": 0.2, "plp0": 1.8}]) == []
    found = errors(pressures=[{"depth": 1, "em": 10000, "pl": 1, "pf": 2}, {"depth": 1}, {"depth": 3, "em": 5}])
    assert "Pressiomètre, 1.0 m : em doit être compris entre 0 (exclu) et 9999.99." in found
    assert "Pressiomètre, 1.0 m : pf doit être inférieur ou égal à pl." in found
    assert "Pressiomètre, 1.0 m : au moins une mesure attendue." in found
    assert "Pressiomètre, 1.0 m : profondeur en double." in found
    assert "Pressiomètre : pl saisi à 1 profondeurs sur 3, à saisir partout ou nulle part." in found


def test_penetrometer_rules():
    reading = {"depth": 0.1, "blowCount": 5}
    assert errors(penetrometer={"machineTypeId": 7, "tipSection": 20, "readings": [reading, {"depth": 0.2, "blowCount": 6}]}) == []
    assert errors(penetrometer={"accessoriesMass": 0, "tipMass": 0, "readings": [reading]}) == []
    assert errors(penetrometer={"tipMass": -1, "readings": [reading]}) == ["Pénétromètre : tipMass doit être positif ou nul."]
    found = errors(penetrometer={"machineTypeId": 9, "rodMass": 0, "readings": [{"depth": 0.3, "blowCount": 2.5}, {"depth": 0.2, "qd": -1}, {"depth": 0.4}]})
    assert found[:2] == ["Pénétromètre : rodMass doit être strictement positif.", "Pénétromètre : type de machine inconnu (9)."]
    assert "Pénétromètre, 0.3 m : nombre de coups entier attendu." in found
    assert "Pénétromètre, 0.2 m : profondeurs croissantes attendues." in found
    assert "Pénétromètre, 0.2 m : Qd strictement positif attendu." in found
    assert "Pénétromètre, 0.4 m : nombre de coups ou Qd attendu." in found


def test_water_levels_need_a_known_datum_a_past_date_and_a_level():
    measure = {"date": "2026-01-15", "depth": 3.2}
    assert errors(waterLevels={"referentiel": "NGF", "measures": [measure, {"date": "2026-02-15", "depth": 9999}]}) == []
    assert errors(waterLevels={"measures": [measure]}) == ["Suivi de nappe : référentiel obligatoire."]
    assert errors(waterLevels={"referentiel": "IGN69", "measures": [{"date": "2026-12-01"}, {"date": "2026-01-01", "depth": 9999, "ref": 3}]}) == [
        "Suivi de nappe : référentiel inconnu (IGN69).",
        "Suivi de nappe, 2026-12-01 : date dans le futur.",
        "Suivi de nappe, 2026-12-01 : niveau en m/TA ou en m/réf. attendu.",
        "Suivi de nappe, 2026-01-01 : ouvrage sec (9999), pas de niveau en m/réf.",
    ]


def test_reference_levels_of_a_survey():
    assert errors(referenceLevels={"standardId": 1, "referentiel": "NGF", "levels": {"eb": {"depth": 1}, "eh": {"depth": 5}, "ee": {"depth": 10}}}) == []
    assert errors(referenceLevels={"levels": {"eh": {"depth": 10}, "ee": {"depth": 5}}}) == [
        "Niveaux caractéristiques : norme obligatoire.",
        "Niveaux caractéristiques : référentiel obligatoire.",
        "Niveaux caractéristiques : EB, EH et EE doivent tous être saisis en m/TA.",
        "Niveaux caractéristiques : EE doit être supérieur ou égal à EH (m/TA).",
    ]


def test_hydrodynamic_tests():
    valid = {"mode": "withdrawal", "longDurationPumping": True, "top": 2, "base": 5, "permeability": 1.5e-5}
    assert errors(hydrodynamics={"tests": [valid]}) == []
    assert errors(hydrodynamics={"tests": [{"mode": "pumping", "top": -1, "base": None, "permeability": 0, "transmissivity": -1}]}) == [
        "Hydrodynamique, essai 1 : mode prélèvement ou injection attendu.",
        "Hydrodynamique, essai 1 : sommet de lanterne négatif.",
        "Hydrodynamique, essai 1 : base de lanterne obligatoire.",
        "Hydrodynamique, essai 1 : perméabilité strictement positive obligatoire.",
        "Hydrodynamique, essai 1 : transmissivité strictement positif attendu.",
    ]
    assert errors(hydrodynamics={"tests": [valid | {"base": 2}]}) == ["Hydrodynamique, essai 1 : la base de la lanterne doit être plus profonde que son sommet."]


@pytest.mark.parametrize(
    "payload",
    [
        {"lithology": {}},
        {"lithology": [{"depthStart": "0", "depthEnd": 1}]},
        {"pressures": [{"em": 3}]},
        {"penetrometer": []},
        {"penetrometer": {"machine": {"hammerMass": 63.5}, "readings": []}},
        {"waterLevels": {"measures": [{"date": "15/01/2026"}]}},
        {"referenceLevels": {"levels": {"xx": {}}}},
        {"hydrodynamics": {"tests": [{"mode": "withdrawal", "longDurationPumping": "oui"}]}},
        {"hydrodynamics": {"tests": [{"facies": "x" * 256}]}},
        {"pressures": [{"depth": 1}] * 2001},
    ],
)
def test_refuses_a_malformed_body(payload):
    with pytest.raises(InvalidRequest):
        survey_data_from_json(payload)
