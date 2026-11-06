# Données saisies d'un site et de ses sondages (édition des données, US-CARTE-40 à 46 du front).
# Lot 1 : listes de référence (référentiels, normes, types de pénétromètre) et niveaux d'eau
# caractéristiques d'un site, ouvrage par ouvrage (table gw_reference_levels, survey_id vide).
# Les règles reprennent celles du front (core/projects/domain/surveyData/referenceLevels.ts) :
# le back refuse ce que le front aurait refusé, même si l'appel ne vient pas du front.

import math
import unicodedata
from dataclasses import dataclass
from typing import Any

from app.core.errors import InvalidRequest, Unprocessable

LEVEL_IDS = ("eb", "eh", "ee")
LEVEL_COLUMNS = ("depth", "ref")
MAX_STRUCTURES = 50
MAX_STRUCTURE_LENGTH = 255
MAX_LEVEL_MAGNITUDE = 10_000


@dataclass(frozen=True)
class Referentiel:
    code: str
    label_fr: str
    label_en: str | None

    def to_json(self) -> dict[str, Any]:
        return {"code": self.code, "labelFr": self.label_fr, "labelEn": self.label_en}


@dataclass(frozen=True)
class Standard:
    id: int
    code: str
    label: str | None

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "code": self.code, "label": self.label}


@dataclass(frozen=True)
class PenetrometerMachineType:
    id: int
    type: str
    hammer_mass: float | None
    hammer_drop_height: float | None
    rod_mass: float | None
    anvil_mass: float | None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "hammerMass": self.hammer_mass,
            "hammerDropHeight": self.hammer_drop_height,
            "rodMass": self.rod_mass,
            "anvilMass": self.anvil_mass,
        }


# Un niveau (EB, EH ou EE) : en m/TA (profondeur sous le terrain) et en m/réf. (cote dans le référentiel).
@dataclass(frozen=True)
class Level:
    depth: float | None = None
    ref: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {"depth": self.depth, "ref": self.ref}


@dataclass(frozen=True)
class StructureLevels:
    structure: str
    standard_id: int | None
    referentiel: str | None
    levels: dict[str, Level]

    def to_json(self) -> dict[str, Any]:
        return {
            "structure": self.structure,
            "standardId": self.standard_id,
            "referentiel": self.referentiel,
            "levels": {level_id: self.levels.get(level_id, Level()).to_json() for level_id in LEVEL_IDS},
        }

    def has_level(self) -> bool:
        return any(getattr(level, column) is not None for level in self.levels.values() for column in LEVEL_COLUMNS)


@dataclass(frozen=True)
class SiteReferenceLevels:
    site_id: str
    ground_elevation: float | None
    structures: list[StructureLevels]

    def to_json(self) -> dict[str, Any]:
        return {"siteId": self.site_id, "groundElevation": self.ground_elevation, "structures": [entry.to_json() for entry in self.structures]}


# Corps de PUT /sites/{id}/reference-levels : { "structures": [ { "structure", "standardId", "referentiel",
# "levels": { "eb": { "depth", "ref" }, "eh": …, "ee": … } } ] }. Forme invalide : 400.
def structures_from_json(payload: dict[str, Any]) -> list[StructureLevels]:
    raw = payload.get("structures")

    if not isinstance(raw, list):
        raise InvalidRequest("structures : liste attendue.")
    if len(raw) > MAX_STRUCTURES:
        raise InvalidRequest(f"structures : {MAX_STRUCTURES} ouvrages au plus.")

    return [_structure_from_json(entry, index) for index, entry in enumerate(raw)]


def _structure_from_json(raw: Any, index: int) -> StructureLevels:
    if not isinstance(raw, dict):
        raise InvalidRequest(f"structures[{index}] : objet attendu.")

    structure = raw.get("structure")
    standard_id = raw.get("standardId")
    referentiel = raw.get("referentiel")
    levels = raw.get("levels", {})

    if not isinstance(structure, str) or len(structure) > MAX_STRUCTURE_LENGTH:
        raise InvalidRequest(f"structures[{index}].structure : texte de {MAX_STRUCTURE_LENGTH} caractères au plus attendu.")
    if standard_id is not None and (isinstance(standard_id, bool) or not isinstance(standard_id, int)):
        raise InvalidRequest(f"structures[{index}].standardId : entier ou null attendu.")
    if referentiel is not None and not isinstance(referentiel, str):
        raise InvalidRequest(f"structures[{index}].referentiel : texte ou null attendu.")
    if not isinstance(levels, dict) or not set(levels) <= set(LEVEL_IDS):
        raise InvalidRequest(f"structures[{index}].levels : objet avec eb, eh, ee attendu.")

    return StructureLevels(
        structure=structure.strip(),
        standard_id=standard_id,
        referentiel=referentiel or None,
        levels={level_id: level_from_json(levels.get(level_id), f"structures[{index}].levels.{level_id}") for level_id in LEVEL_IDS},
    )


def level_from_json(raw: Any, path: str) -> Level:
    if raw is None:
        return Level()
    if not isinstance(raw, dict) or not set(raw) <= set(LEVEL_COLUMNS):
        raise InvalidRequest(f"{path} : objet avec depth et ref attendu.")
    return Level(depth=_number(raw.get("depth"), f"{path}.depth"), ref=_number(raw.get("ref"), f"{path}.ref"))


def _number(raw: Any, path: str) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not math.isfinite(raw) or abs(raw) > MAX_LEVEL_MAGNITUDE:
        raise InvalidRequest(f"{path} : nombre attendu (|x| ≤ {MAX_LEVEL_MAGNITUDE}).")
    return float(raw)


# Cote du terrain naturel du même corps : « groundElevation » absent = altitude du site inchangée,
# null = altitude effacée, nombre = nouvelle altitude (|x| ≤ 10 000 m, comme la géolocalisation).
@dataclass(frozen=True)
class GroundElevationChange:
    provided: bool
    value: float | None = None


def ground_elevation_from_json(payload: dict[str, Any]) -> GroundElevationChange:
    if "groundElevation" not in payload:
        return GroundElevationChange(provided=False)
    return GroundElevationChange(provided=True, value=_number(payload["groundElevation"], "groundElevation"))


# Règles métier (422) : ouvrage nommé et unique dans le site (casse, accents et espaces ignorés) ;
# norme et référentiel dès qu'un niveau est saisi, et connus ; EE ≥ EH ≥ EB dans chaque colonne
# (règle de la tâche appliquée aux valeurs telles que saisies, tranchée le 06/11/2026).
def structure_errors(structures: list[StructureLevels], standard_ids: set[int], referentiel_codes: set[str]) -> list[str]:
    errors: list[str] = []
    names = [_comparable(entry.structure) for entry in structures]

    for index, entry in enumerate(structures):
        label = entry.structure or f"ouvrage n° {index + 1}"
        if names[index] == "":
            errors.append(f"Ouvrage n° {index + 1} : nom obligatoire.")
        elif names.count(names[index]) > 1:
            errors.append(f"{label} : ouvrage en double dans le site.")
        if entry.has_level() and entry.standard_id is None:
            errors.append(f"{label} : norme obligatoire.")
        if entry.has_level() and entry.referentiel is None:
            errors.append(f"{label} : référentiel obligatoire.")
        if entry.standard_id is not None and entry.standard_id not in standard_ids:
            errors.append(f"{label} : norme inconnue ({entry.standard_id}).")
        if entry.referentiel is not None and entry.referentiel not in referentiel_codes:
            errors.append(f"{label} : référentiel inconnu ({entry.referentiel}).")
        errors.extend(f"{label} : {message}" for message in level_order_errors(entry.levels))

    return errors


def level_order_errors(levels: dict[str, Level]) -> list[str]:
    errors = []
    for column, unit in (("depth", "m/TA"), ("ref", "m/réf.")):
        for upper, lower in (("eh", "eb"), ("ee", "eh")):
            upper_value = getattr(levels.get(upper, Level()), column)
            lower_value = getattr(levels.get(lower, Level()), column)
            if upper_value is not None and lower_value is not None and upper_value < lower_value:
                errors.append(f"{upper.upper()} doit être supérieur ou égal à {lower.upper()} ({unit}).")
    return errors


def checked_structures(structures: list[StructureLevels], standard_ids: set[int], referentiel_codes: set[str]) -> list[StructureLevels]:
    errors = structure_errors(structures, standard_ids, referentiel_codes)
    if errors:
        raise Unprocessable(" ".join(errors))
    return structures


def _comparable(name: str) -> str:
    without_accents = "".join(char for char in unicodedata.normalize("NFD", name) if unicodedata.category(char) != "Mn")
    return " ".join(without_accents.split()).lower()
