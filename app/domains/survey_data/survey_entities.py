# Données saisies d'un sondage (US-CARTE-41 à 45 du front) : lithologie, essais pressiométriques, essai
# pénétrométrique, suivi de nappe, niveaux caractéristiques, caractéristiques hydrodynamiques.
# Contrat de GET et PUT /survey-data/{id} ; forme invalide : 400 (InvalidRequest). Les règles métier
# (422) sont dans survey_rules.py.

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.core.errors import InvalidRequest
from app.domains.survey_data.entities import LEVEL_IDS, Level, level_from_json

MAX_ROWS = 2_000
MAX_TEXT_LENGTH = 255
MAX_MAGNITUDE = 1e6
HYDRO_MODES = ("withdrawal", "injection")
MACHINE_FIELDS = ("hammerDropHeight", "hammerMass", "anvilMass", "rodMass", "tipSection")


@dataclass(frozen=True)
class LithologyLayer:
    depth_start: float
    depth_end: float
    description: str

    def to_json(self) -> dict[str, Any]:
        return {"depthStart": self.depth_start, "depthEnd": self.depth_end, "description": self.description}


@dataclass(frozen=True)
class PressureTest:
    depth: float
    em: float | None = None
    pl: float | None = None
    pf: float | None = None
    p0: float | None = None
    plp0: float | None = None
    pfp0: float | None = None

    def measures(self) -> dict[str, float | None]:
        return {"em": self.em, "pl": self.pl, "pf": self.pf, "p0": self.p0, "plp0": self.plp0, "pfp0": self.pfp0}

    def to_json(self) -> dict[str, Any]:
        return {"depth": self.depth} | self.measures()


@dataclass(frozen=True)
class PenetrometerReading:
    depth: float
    blow_count: float | None = None
    qd: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {"depth": self.depth, "blowCount": self.blow_count, "qd": self.qd}


@dataclass(frozen=True)
class PenetrometerTest:
    machine_type_id: int | None
    machine: dict[str, float | None]
    readings: list[PenetrometerReading]

    def to_json(self) -> dict[str, Any]:
        return {"machineTypeId": self.machine_type_id} | self.machine | {"readings": [reading.to_json() for reading in self.readings]}

    def is_empty(self) -> bool:
        return self.machine_type_id is None and all(value is None for value in self.machine.values()) and not self.readings


@dataclass(frozen=True)
class WaterLevelMeasure:
    date: date
    depth: float | None = None
    ref: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {"date": self.date.isoformat(), "depth": self.depth, "ref": self.ref}


@dataclass(frozen=True)
class WaterLevels:
    referentiel: str | None = None
    measures: list[WaterLevelMeasure] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"referentiel": self.referentiel, "measures": [measure.to_json() for measure in self.measures]}


@dataclass(frozen=True)
class SurveyReferenceLevels:
    standard_id: int | None = None
    referentiel: str | None = None
    levels: dict[str, Level] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "standardId": self.standard_id,
            "referentiel": self.referentiel,
            "levels": {level_id: self.levels.get(level_id, Level()).to_json() for level_id in LEVEL_IDS},
        }

    def has_level(self) -> bool:
        return any(value is not None for level in self.levels.values() for value in (level.depth, level.ref))

    def is_empty(self) -> bool:
        return not self.has_level() and self.standard_id is None and self.referentiel is None


@dataclass(frozen=True)
class HydrodynamicTest:
    mode: str
    long_duration_pumping: bool
    top: float | None
    base: float | None
    permeability: float | None
    transmissivity: float | None = None
    storage: float | None = None
    facies: str | None = None
    notes: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "longDurationPumping": self.long_duration_pumping,
            "top": self.top,
            "base": self.base,
            "permeability": self.permeability,
            "transmissivity": self.transmissivity,
            "storage": self.storage,
            "facies": self.facies,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class Hydrodynamics:
    tests: list[HydrodynamicTest] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"tests": [test.to_json() for test in self.tests]}


@dataclass(frozen=True)
class SurveyData:
    lithology: list[LithologyLayer]
    pressures: list[PressureTest]
    penetrometer: PenetrometerTest | None
    water_levels: WaterLevels
    reference_levels: SurveyReferenceLevels
    hydrodynamics: Hydrodynamics

    def to_json(self) -> dict[str, Any]:
        return {
            "lithology": [layer.to_json() for layer in self.lithology],
            "pressures": [test.to_json() for test in self.pressures],
            "penetrometer": None if self.penetrometer is None else self.penetrometer.to_json(),
            "waterLevels": self.water_levels.to_json(),
            "referenceLevels": self.reference_levels.to_json(),
            "hydrodynamics": self.hydrodynamics.to_json(),
        }


@dataclass(frozen=True)
class SavedSurveyData:
    survey_id: str
    ground_elevation: float | None
    data: SurveyData

    def to_json(self) -> dict[str, Any]:
        return {"surveyId": self.survey_id, "groundElevation": self.ground_elevation} | self.data.to_json()


def _number(raw: Any, path: str, required: bool = False) -> float | None:
    if raw is None:
        if required:
            raise InvalidRequest(f"{path} : nombre attendu.")
        return None
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not math.isfinite(raw) or abs(raw) > MAX_MAGNITUDE:
        raise InvalidRequest(f"{path} : nombre attendu.")
    return float(raw)


def _text(raw: Any, path: str) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or len(raw) > MAX_TEXT_LENGTH:
        raise InvalidRequest(f"{path} : texte de {MAX_TEXT_LENGTH} caractères au plus attendu.")
    return raw.strip() or None


def _bool(raw: Any, path: str) -> bool:
    if not isinstance(raw, bool):
        raise InvalidRequest(f"{path} : booléen attendu.")
    return raw


def _int_or_none(raw: Any, path: str) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise InvalidRequest(f"{path} : entier ou null attendu.")
    return raw


def _objects(raw: Any, path: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) > MAX_ROWS or not all(isinstance(entry, dict) for entry in raw):
        raise InvalidRequest(f"{path} : liste d'objets attendue ({MAX_ROWS} au plus).")
    return raw


def _object(raw: Any, path: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise InvalidRequest(f"{path} : objet attendu.")
    return raw


def _date(raw: Any, path: str) -> date:
    if not isinstance(raw, str):
        raise InvalidRequest(f"{path} : date AAAA-MM-JJ attendue.")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise InvalidRequest(f"{path} : date AAAA-MM-JJ attendue.") from None


def survey_data_from_json(payload: dict[str, Any]) -> SurveyData:
    penetrometer = payload.get("penetrometer")
    water = _object(payload.get("waterLevels", {}), "waterLevels")
    reference = _object(payload.get("referenceLevels", {}), "referenceLevels")
    hydro = _object(payload.get("hydrodynamics", {}), "hydrodynamics")
    levels = _object(reference.get("levels", {}), "referenceLevels.levels")
    if not set(levels) <= set(LEVEL_IDS):
        raise InvalidRequest("referenceLevels.levels : eb, eh, ee attendus.")

    return SurveyData(
        lithology=[
            LithologyLayer(
                depth_start=_number(row.get("depthStart"), f"lithology[{index}].depthStart", required=True),
                depth_end=_number(row.get("depthEnd"), f"lithology[{index}].depthEnd", required=True),
                description=_text(row.get("description"), f"lithology[{index}].description") or "",
            )
            for index, row in enumerate(_objects(payload.get("lithology", []), "lithology"))
        ],
        pressures=[
            PressureTest(
                depth=_number(row.get("depth"), f"pressures[{index}].depth", required=True),
                **{key: _number(row.get(key), f"pressures[{index}].{key}") for key in ("em", "pl", "pf", "p0", "plp0", "pfp0")},
            )
            for index, row in enumerate(_objects(payload.get("pressures", []), "pressures"))
        ],
        penetrometer=None if penetrometer is None else _penetrometer_from_json(_object(penetrometer, "penetrometer")),
        water_levels=WaterLevels(
            referentiel=_text(water.get("referentiel"), "waterLevels.referentiel"),
            measures=[
                WaterLevelMeasure(
                    date=_date(row.get("date"), f"waterLevels.measures[{index}].date"),
                    depth=_number(row.get("depth"), f"waterLevels.measures[{index}].depth"),
                    ref=_number(row.get("ref"), f"waterLevels.measures[{index}].ref"),
                )
                for index, row in enumerate(_objects(water.get("measures", []), "waterLevels.measures"))
            ],
        ),
        reference_levels=SurveyReferenceLevels(
            standard_id=_int_or_none(reference.get("standardId"), "referenceLevels.standardId"),
            referentiel=_text(reference.get("referentiel"), "referenceLevels.referentiel"),
            levels={level_id: level_from_json(levels.get(level_id), f"referenceLevels.levels.{level_id}") for level_id in LEVEL_IDS},
        ),
        hydrodynamics=Hydrodynamics(
            tests=[
                HydrodynamicTest(
                    mode=_text(row.get("mode"), f"hydrodynamics.tests[{index}].mode") or "",
                    long_duration_pumping=_bool(row.get("longDurationPumping", False), f"hydrodynamics.tests[{index}].longDurationPumping"),
                    top=_number(row.get("top"), f"hydrodynamics.tests[{index}].top"),
                    base=_number(row.get("base"), f"hydrodynamics.tests[{index}].base"),
                    permeability=_number(row.get("permeability"), f"hydrodynamics.tests[{index}].permeability"),
                    transmissivity=_number(row.get("transmissivity"), f"hydrodynamics.tests[{index}].transmissivity"),
                    storage=_number(row.get("storage"), f"hydrodynamics.tests[{index}].storage"),
                    facies=_text(row.get("facies"), f"hydrodynamics.tests[{index}].facies"),
                    notes=_text(row.get("notes"), f"hydrodynamics.tests[{index}].notes"),
                )
                for index, row in enumerate(_objects(hydro.get("tests", []), "hydrodynamics.tests"))
            ],
        ),
    )


PENETROMETER_KEYS = {"machineTypeId", "readings", *MACHINE_FIELDS}


def _penetrometer_from_json(raw: dict[str, Any]) -> PenetrometerTest:
    unknown = set(raw) - PENETROMETER_KEYS
    if unknown:
        raise InvalidRequest(f"penetrometer : champs inconnus ({', '.join(sorted(unknown))}).")
    return PenetrometerTest(
        machine_type_id=_int_or_none(raw.get("machineTypeId"), "penetrometer.machineTypeId"),
        machine={name: _number(raw.get(name), f"penetrometer.{name}") for name in MACHINE_FIELDS},
        readings=[
            PenetrometerReading(
                depth=_number(row.get("depth"), f"penetrometer.readings[{index}].depth", required=True),
                blow_count=_number(row.get("blowCount"), f"penetrometer.readings[{index}].blowCount"),
                qd=_number(row.get("qd"), f"penetrometer.readings[{index}].qd"),
            )
            for index, row in enumerate(_objects(raw.get("readings", []), "penetrometer.readings"))
        ],
    )
