import pytest

from app.core.errors import InvalidRequest, Unprocessable
from app.domains.survey_data.entities import (
    Level,
    StructureLevels,
    checked_structures,
    level_completeness_errors,
    level_order_errors,
    structure_errors,
    structures_from_json,
)

STANDARDS = {1, 2}
REFERENTIELS = {"NGF", "LUREF"}


COMPLETE = {"eb": {"depth": 1}, "eh": {"depth": 5}, "ee": {"depth": 10}}


def structure(name="Bât. A", standard_id=1, referentiel="NGF", **levels):
    chosen = levels or COMPLETE
    return StructureLevels(structure=name, standard_id=standard_id, referentiel=referentiel, levels={key: Level(**value) for key, value in chosen.items()})


def test_reads_a_structure_and_fills_missing_levels():
    [entry] = structures_from_json(
        {"structures": [{"structure": "  Bât. A ", "standardId": 2, "referentiel": "NGF", "levels": {"eb": {"depth": 5, "ref": 40.5}}}]}
    )
    assert entry.structure == "Bât. A"
    assert entry.standard_id == 2
    assert entry.levels["eb"] == Level(depth=5.0, ref=40.5)
    assert entry.levels["ee"] == Level()
    assert entry.to_json()["levels"]["eh"] == {"depth": None, "ref": None}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"structures": {}},
        {"structures": ["Bât. A"]},
        {"structures": [{"structure": 3}]},
        {"structures": [{"structure": "A", "standardId": "1"}]},
        {"structures": [{"structure": "A", "standardId": True}]},
        {"structures": [{"structure": "A", "referentiel": 1}]},
        {"structures": [{"structure": "A", "levels": {"xx": {}}}]},
        {"structures": [{"structure": "A", "levels": {"eb": {"depth": "5"}}}]},
        {"structures": [{"structure": "A", "levels": {"eb": {"depth": 1e9}}}]},
        {"structures": [{"structure": "A", "levels": {"eb": {"height": 1}}}]},
        {"structures": [{"structure": "x" * 256}]},
        {"structures": [{"structure": f"S{index}"} for index in range(51)]},
    ],
)
def test_refuses_a_malformed_body(payload):
    with pytest.raises(InvalidRequest):
        structures_from_json(payload)


def test_accepts_ee_above_eh_above_eb_in_each_column():
    assert level_order_errors({"eb": Level(depth=5, ref=40), "eh": Level(depth=12, ref=40), "ee": Level(depth=15, ref=41)}) == []


def test_flags_ee_below_eh_or_eh_below_eb_on_entered_values():
    assert level_order_errors({"eh": Level(depth=10), "ee": Level(depth=5)}) == ["EE doit être supérieur ou égal à EH (m/TA)."]
    assert level_order_errors({"eb": Level(ref=45), "eh": Level(ref=40)}) == ["EH doit être supérieur ou égal à EB (m/réf.)."]
    assert level_order_errors({"eb": Level(depth=5), "ee": Level(depth=1)}) == []


def test_structure_names_are_required_and_unique_ignoring_case_accents_and_spaces():
    errors = structure_errors([structure("Bât. A"), structure(" bat.  a"), structure("")], STANDARDS, REFERENTIELS)
    assert errors == ["Bât. A : ouvrage en double dans le site.", " bat.  a : ouvrage en double dans le site.", "Ouvrage n° 3 : nom obligatoire."]


def test_standard_and_referentiel_are_required_with_the_levels_and_must_exist():
    assert structure_errors([structure(standard_id=None, referentiel=None)], STANDARDS, REFERENTIELS) == [
        "Bât. A : norme obligatoire.",
        "Bât. A : référentiel obligatoire.",
    ]
    assert structure_errors([structure(standard_id=9, referentiel="IGN69")], STANDARDS, REFERENTIELS) == [
        "Bât. A : norme inconnue (9).",
        "Bât. A : référentiel inconnu (IGN69).",
    ]


def test_eb_eh_ee_are_all_required_at_the_site_and_a_started_column_must_be_complete():
    assert level_completeness_errors({}, required=True) == ["EB, EH et EE obligatoires (en m/TA, en m/réf. ou les deux)."]
    assert level_completeness_errors({}, required=False) == []
    assert level_completeness_errors({"eb": Level(depth=1), "eh": Level(depth=5, ref=40)}, required=False) == [
        "EB, EH et EE doivent tous être saisis en m/TA.",
        "EB, EH et EE doivent tous être saisis en m/réf.",
    ]
    assert level_completeness_errors({"eb": Level(ref=30), "eh": Level(ref=38), "ee": Level(ref=45)}, required=True) == []
    assert structure_errors([structure(eb={"depth": 1})], STANDARDS, REFERENTIELS) == ["Bât. A : EB, EH et EE doivent tous être saisis en m/TA."]


def test_checked_structures_raises_unprocessable_with_every_error():
    with pytest.raises(Unprocessable, match="EE doit être supérieur ou égal à EH"):
        checked_structures([structure(eb={"depth": 1}, eh={"depth": 10}, ee={"depth": 5})], STANDARDS, REFERENTIELS)
