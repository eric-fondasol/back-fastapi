# Logique métier du domaine map : appelé par routes.py, appelle sources.py (API Solscore v2).
# Les points de l'API Solscore sont renvoyés au front sous les noms de propriétés qu'il connaît
# (contrat de l'ancien back : uuid, affaire_numero, nom, site_uuid…).
#
# Filtres : l'API Solscore exige tous les indicateurs demandés à la fois (ET). Le panneau du front
# veut un OU dans la section « Sondages » (pressiométrique ou pénétrométrique) : une seule nature
# passe telle quelle à l'API ; plusieurs natures sont filtrées ici (sondages) ou demandées une à une
# puis réunies (sites). Niveaux d'eau et origine : une seule valeur cochée filtre, les deux ou
# aucune ne filtrent pas.

from collections.abc import Callable
from typing import Any

from app.domains.map import sources
from app.domains.map.schemas import Bounds, SurveyFilters

SITES_ROUTE = "/general/searchSitesByAreaDetails"
SURVEYS_ROUTE = "/general/searchSurveysByAreaDetails"
SURVEY_POSITIONS_ROUTE = "/general/searchSurveysByArea"

# Nature de sondage du panneau → indicateur de l'API Solscore.
KIND_FLAGS = {
    "pressuremeter": "has_pressuremeter",
    "penetrometer": "has_penetrometer",
    "lithology": "has_lithology",
    "pzEquipment": "has_pz_equipment",
}

Properties = Callable[[dict[str, Any]], dict[str, Any]]


# Propriétés d'un site pour le front, à partir de celles de l'API Solscore.
def _site_properties(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "uuid": _text(properties.get("id")),
        "affaire_id": _text(properties.get("project_id")),
        "affaire_numero": properties.get("project_number"),
        "affaire_nom": properties.get("project_description"),
    }


# Les indicateurs de nature valent toujours true ou false pour le front, jamais null :
# il en tire le symbole du sondage (pressiométrique, pénétrométrique, autre).
def _survey_properties(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _text(properties.get("id")),
        "nom": properties.get("name"),
        "site_uuid": _text(properties.get("site_id")),
        "has_mesure_pressiometrique": bool(properties.get("has_pressuremeter")),
        "has_essai_penetro_dynamique": bool(properties.get("has_penetrometer")),
        "has_lithologie": bool(properties.get("has_lithology")),
    }


def _no_properties(_: dict[str, Any]) -> dict[str, Any]:
    return {}


# Indicateurs exigés hors nature de sondage : niveaux d'eau et origine.
def _common_flags(filters: SurveyFilters) -> dict[str, bool]:
    flags = {}
    if len(set(filters.waterLevels)) == 1:
        flags["has_water_levels"] = filters.waterLevels[0] == "present"
    if len(set(filters.origins)) == 1:
        flags["is_survey_fondasol"] = filters.origins[0] == "fondasol"
    return flags


def _kind_flags(filters: SurveyFilters) -> list[str]:
    return [KIND_FLAGS[kind] for kind in dict.fromkeys(filters.surveyKinds)]


# L'API Solscore n'a pas de route des sites sans détails : on prend les détails sans les renvoyer.
# Plusieurs natures : une demande par nature, les sites réunis sans doublon.
def sites_in_area(bounds: Bounds, with_details: bool, filters: SurveyFilters = SurveyFilters()) -> list[dict]:
    common, kinds = _common_flags(filters), _kind_flags(filters)
    if len(kinds) <= 1:
        found = sources.area_features(SITES_ROUTE, bounds, common | {kind: True for kind in kinds})
    else:
        found = _union(
            (feature for kind in kinds for feature in sources.area_features(SITES_ROUTE, bounds, common | {kind: True})),
            key=lambda feature: (feature.get("properties") or {}).get("id"),
        )
    return _features(found, _site_properties if with_details else _no_properties)


# Plusieurs natures : les sondages détaillés sont lus une fois puis gardés s'ils ont l'une d'elles ;
# les positions seules n'ont pas les indicateurs, on passe alors aussi par les détails.
def surveys_in_area(bounds: Bounds, with_details: bool, filters: SurveyFilters = SurveyFilters()) -> list[dict]:
    common, kinds = _common_flags(filters), _kind_flags(filters)
    properties = _survey_properties if with_details else _no_properties
    if len(kinds) <= 1:
        route = SURVEYS_ROUTE if with_details else SURVEY_POSITIONS_ROUTE
        return _features(sources.area_features(route, bounds, common | {kind: True for kind in kinds}), properties)
    found = sources.area_features(SURVEYS_ROUTE, bounds, common)
    return _features(
        [feature for feature in found if any((feature.get("properties") or {}).get(kind) for kind in kinds)],
        properties,
    )


def _union(features, key) -> list[dict]:
    seen, kept = set(), []
    for feature in features:
        identifier = key(feature)
        if identifier not in seen:
            seen.add(identifier)
            kept.append(feature)
    return kept


# Points GeoJSON pour le front : position arrondie à 6 décimales (environ 11 cm, suffisant pour la
# carte et plus léger à transférer), propriétés renommées.
def _features(found: list[dict], properties: Properties) -> list[dict]:
    features = []
    for feature in found:
        longitude, latitude = feature["geometry"]["coordinates"][:2]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(longitude, 6), round(latitude, 6)]},
                "properties": properties(feature.get("properties") or {}),
            }
        )
    return features


def _text(value: Any) -> str | None:
    return None if value is None else str(value)
