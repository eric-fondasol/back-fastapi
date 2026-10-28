# Objets métier du profil : préférences, couches de « Mes couches », adresses favorites.
# Les règles de validation et leurs messages sont repris à l'identique du back Symfony
# (UserPreferences, MapLayerSetting, LayerId, FavoriteAddress) : le front affiche ces messages.

import json
import math
import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from app.core.errors import InvalidRequest

LOCALES = ["fr", "en"]
THEMES = ["light", "dark", "system"]
MAX_LAYERS = 100
MAX_PREFERENCE_LENGTH = 100
MAX_ADDRESS_TEXT_LENGTH = 500
FAVORITE_ADDRESS_LIMIT = 20
LAYER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
PREFERENCE_FIELDS = ["locale", "theme", "defaultTerritory", "mapStyle", "mapLayers", "extra"]


# Un nombre JSON : en Python, True et False sont aussi des entiers, d'où l'exclusion explicite.
def is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def layer_id(value: Any) -> str:
    if not isinstance(value, str) or not LAYER_ID.fullmatch(value):
        raise InvalidRequest("Identifiant de couche invalide.")

    return value


# Une couche de « Mes couches » : visible ou non, et son opacité entre 0 et 1.
@dataclass(frozen=True)
class MapLayerSetting:
    layer_id: str
    visible: bool
    opacity: float

    @classmethod
    def of(cls, raw: Any) -> "MapLayerSetting":
        if not isinstance(raw, dict):
            raise InvalidRequest("Une couche doit etre un objet.")

        visible, opacity = raw.get("visible"), raw.get("opacity")

        if not isinstance(visible, bool):
            raise InvalidRequest("visible doit etre un booleen.")

        if not is_number(opacity) or not 0 <= opacity <= 1:
            raise InvalidRequest("opacity doit etre compris entre 0 et 1.")

        return cls(layer_id(raw.get("layerId")), visible, float(opacity))

    def to_json(self) -> dict[str, Any]:
        return {"layerId": self.layer_id, "visible": self.visible, "opacity": self.opacity}


@dataclass(frozen=True)
class Preferences:
    locale: str | None = None
    theme: str | None = None
    default_territory: str | None = None
    map_style: str | None = None
    map_layers: list[MapLayerSetting] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    # Applique un PATCH : seules les préférences envoyées changent ; null en vide une.
    def revised_with(self, changes: dict[str, Any]) -> "Preferences":
        unknown = [name for name in changes if name not in PREFERENCE_FIELDS]

        if unknown:
            raise InvalidRequest(f"Preference inconnue : {', '.join(unknown)}.")

        revised = self

        if "locale" in changes:
            revised = replace(revised, locale=_choice(changes["locale"], LOCALES, "locale"))
        if "theme" in changes:
            revised = replace(revised, theme=_choice(changes["theme"], THEMES, "theme"))
        if "defaultTerritory" in changes:
            revised = replace(revised, default_territory=_text(changes["defaultTerritory"], "defaultTerritory"))
        if "mapStyle" in changes:
            revised = replace(revised, map_style=_text(changes["mapStyle"], "mapStyle"))
        if "mapLayers" in changes:
            revised = replace(revised, map_layers=_layers(changes["mapLayers"]))
        if "extra" in changes:
            revised = replace(revised, extra=_extra(changes["extra"]))

        return revised

    def to_json(self) -> dict[str, Any]:
        return {
            "locale": self.locale,
            "theme": self.theme,
            "defaultTerritory": self.default_territory,
            "mapStyle": self.map_style,
            "mapLayers": [layer.to_json() for layer in self.map_layers],
            "extra": self.extra,
        }


def _choice(value: Any, allowed: list[str], name: str) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str) or value not in allowed:
        raise InvalidRequest(f"{name} doit valoir {', '.join(allowed)}.")

    return value


def _text(value: Any, name: str) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str) or len(value) > MAX_PREFERENCE_LENGTH:
        raise InvalidRequest(f"{name} doit etre un texte de {MAX_PREFERENCE_LENGTH} caracteres au plus.")

    return value


# Une couche envoyée deux fois n'est gardée qu'une fois : la première l'emporte.
def _layers(value: Any) -> list[MapLayerSetting]:
    if value is None:
        return []

    if not isinstance(value, list) or len(value) > MAX_LAYERS:
        raise InvalidRequest(f"mapLayers doit etre une liste de {MAX_LAYERS} couches au plus.")

    layers: dict[str, MapLayerSetting] = {}

    for raw in value:
        layer = MapLayerSetting.of(raw)
        layers.setdefault(layer.layer_id, layer)

    return list(layers.values())


def _extra(value: Any) -> dict[str, Any]:
    if value is None or value == []:
        return {}

    if not isinstance(value, dict):
        raise InvalidRequest("extra doit etre un objet.")

    return value


# Une adresse favorite, identifiée chez le géocodeur par external_id (une seule fois par agent).
@dataclass(frozen=True)
class FavoriteAddress:
    id: str
    external_id: str
    label: str
    name: str | None
    context: str | None
    kind: str | None
    longitude: float
    latitude: float
    created_at: datetime

    @classmethod
    def of(cls, address_id: str, raw: dict[str, Any], created_at: datetime) -> "FavoriteAddress":
        external_id = _required(raw.get("externalId"), "externalId")
        label = _required(raw.get("label"), "label")
        longitude, latitude = raw.get("longitude"), raw.get("latitude")

        if not is_number(longitude) or not is_number(latitude):
            raise InvalidRequest("longitude et latitude sont requises.")

        if not -180 <= longitude <= 180:
            raise InvalidRequest(f"Longitude hors bornes : {longitude:f}")

        if not -90 <= latitude <= 90:
            raise InvalidRequest(f"Latitude hors bornes : {latitude:f}")

        return cls(
            address_id,
            external_id,
            label,
            _optional(raw.get("name"), "name"),
            _optional(raw.get("context"), "context"),
            _optional(raw.get("kind"), "kind"),
            float(longitude),
            float(latitude),
            created_at,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "externalId": self.external_id,
            "label": self.label,
            "name": self.name,
            "context": self.context,
            "kind": self.kind,
            "longitude": self.longitude,
            "latitude": self.latitude,
            "createdAt": self.created_at.isoformat(timespec="seconds"),
        }


def _required(value: Any, name: str) -> str:
    text = _optional(value, name)

    if text is None or not text.strip():
        raise InvalidRequest(f"{name} est requis.")

    return text


def _optional(value: Any, name: str) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str) or len(value) > MAX_ADDRESS_TEXT_LENGTH:
        raise InvalidRequest(f"{name} doit etre un texte de {MAX_ADDRESS_TEXT_LENGTH} caracteres au plus.")

    return value


@dataclass(frozen=True)
class Favorites:
    project_ids: list[str]
    layer_ids: list[str]
    addresses: list[FavoriteAddress]

    def to_json(self) -> dict[str, Any]:
        return {
            "projects": self.project_ids,
            "layers": self.layer_ids,
            "addresses": [address.to_json() for address in self.addresses],
        }


# Couches ajoutées par l'agent (ADR-0035 du front). Flux (WMS, WMTS, XYZ) : l'adresse n'est jamais
# appelée par le back, le navigateur charge les tuiles lui-même. Fichiers (ADR-0037 du front) : le
# navigateur convertit le fichier en GeoJSON WGS 84, le back le contrôle et le range en jsonb.
USER_LAYER_LIMIT = 50
USER_LAYER_PREFIX = "user:"
MAX_LAYER_NAME_LENGTH = 100
MAX_LAYER_URL_LENGTH = 2000
MAX_LAYER_PARAM_LENGTH = 200
FLOW_KINDS = ["wms", "wmts", "xyz"]
TILE_FORMATS = ["image/png", "image/jpeg"]
WMS_VERSIONS = ["1.3.0", "1.1.1"]
XYZ_PLACEHOLDERS = ["{z}", "{x}", "{y}"]
FILE_KIND = "file"
MAX_GEOJSON_BYTES = 5 * 1024 * 1024
MAX_FEATURES = 50_000
MAX_ORIGINAL_NAME_LENGTH = 255
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
# Style d'une couche fichier (ADR-0039 du front) : (nom, minimum, maximum) des réglages numériques.
STYLE_NUMBERS = [("lineWidth", 0.5, 10), ("pointRadius", 1, 20)]
MAX_LABEL_FIELD_LENGTH = 100
GEOMETRY_DEPTHS = {"Point": 0, "MultiPoint": 1, "LineString": 1, "MultiLineString": 2, "Polygon": 2, "MultiPolygon": 3}


@dataclass(frozen=True)
class UserLayer:
    id: str
    name: str
    kind: str
    url: str | None
    params: dict[str, str]
    created_at: datetime
    original_name: str | None = None
    bounds: tuple[float, float, float, float] | None = None
    # Jamais renvoyé par to_json : la liste des couches reste légère, le GeoJSON a sa propre route.
    geojson: dict[str, Any] | None = None
    style: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def of(cls, layer_uuid: str, raw: dict[str, Any], created_at: datetime) -> "UserLayer":
        kind = raw.get("kind")

        if kind == FILE_KIND:
            geojson, bounds = geojson_document(raw.get("geojson"))
            return cls(
                layer_uuid,
                layer_name(raw.get("name")),
                kind,
                None,
                {},
                created_at,
                _original_name(raw.get("originalName")),
                bounds,
                geojson,
            )

        if kind not in FLOW_KINDS:
            raise InvalidRequest(f"kind doit valoir {', '.join(FLOW_KINDS + [FILE_KIND])}.")

        url = _layer_url(raw.get("url"), kind)
        return cls(layer_uuid, layer_name(raw.get("name")), kind, url, _flow_params(kind, raw.get("params")), created_at)

    @property
    def layer_id(self) -> str:
        return USER_LAYER_PREFIX + self.id

    def to_json(self) -> dict[str, Any]:
        common = {"id": self.id, "layerId": self.layer_id, "name": self.name, "kind": self.kind}
        created_at = {"createdAt": self.created_at.isoformat(timespec="seconds")}

        if self.kind == FILE_KIND:
            return {
                **common,
                "originalName": self.original_name,
                "bounds": list(self.bounds) if self.bounds else None,
                "style": self.style,
                **created_at,
            }

        return {**common, "url": self.url, "params": self.params, **created_at}


def layer_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > MAX_LAYER_NAME_LENGTH:
        raise InvalidRequest(f"name doit etre un texte de 1 a {MAX_LAYER_NAME_LENGTH} caracteres.")

    return value.strip()


# https seulement : une page https ne charge pas de tuiles http.
def _layer_url(value: Any, kind: str) -> str:
    if not isinstance(value, str) or len(value) > MAX_LAYER_URL_LENGTH or not re.match(r"https://[^\s/?#]+[^\s]*$", value):
        raise InvalidRequest("url doit etre une adresse https.")

    # Un point ou une virgule recopiés avec la fin d'une phrase rendent toutes les tuiles introuvables.
    if value[-1] in ".,;:":
        raise InvalidRequest("url ne doit pas se terminer par un signe de ponctuation.")

    if kind == "xyz" and not all(placeholder in value for placeholder in XYZ_PLACEHOLDERS):
        raise InvalidRequest("url d'un flux XYZ doit contenir {z}, {x} et {y}.")

    return value


# Paramètres attendus par type de flux : (nom, requis, valeurs permises ou None pour un texte libre).
FLOW_PARAMS: dict[str, list[tuple[str, bool, list[str] | None]]] = {
    "wms": [("layers", True, None), ("styles", False, None), ("format", False, TILE_FORMATS), ("version", False, WMS_VERSIONS)],
    "wmts": [("layer", True, None), ("style", True, None), ("tileMatrixSet", True, None), ("format", False, TILE_FORMATS)],
    "xyz": [],
}


def _flow_params(kind: str, value: Any) -> dict[str, str]:
    if value is None:
        value = {}

    if not isinstance(value, dict):
        raise InvalidRequest("params doit etre un objet.")

    expected = FLOW_PARAMS[kind] + [("attribution", False, None)]
    unknown = [name for name in value if name not in {name for name, _, _ in expected}]

    if unknown:
        raise InvalidRequest(f"Parametre inconnu : {', '.join(unknown)}.")

    params: dict[str, str] = {}

    for name, required, allowed in expected:
        raw = value.get(name)

        if raw is None or raw == "":
            if required:
                raise InvalidRequest(f"params.{name} est requis.")
            continue

        if not isinstance(raw, str) or len(raw) > MAX_LAYER_PARAM_LENGTH:
            raise InvalidRequest(f"params.{name} doit etre un texte de {MAX_LAYER_PARAM_LENGTH} caracteres au plus.")

        if allowed is not None and raw not in allowed:
            raise InvalidRequest(f"params.{name} doit valoir {', '.join(allowed)}.")

        params[name] = raw.strip() if allowed is None else raw

    return params


def _original_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > MAX_ORIGINAL_NAME_LENGTH:
        raise InvalidRequest(f"originalName doit etre un texte de 1 a {MAX_ORIGINAL_NAME_LENGTH} caracteres.")

    return value.strip()


# GeoJSON WGS 84 (RFC 7946) : collection d'objets aux géométries simples, coordonnées en degrés.
# On ne garde que type, geometry et properties : tout autre membre (crs, bbox, style…) est écarté.
# Renvoie le document nettoyé et son emprise (ouest, sud, est, nord).
def geojson_document(value: Any) -> tuple[dict[str, Any], tuple[float, float, float, float]]:
    if not isinstance(value, dict) or value.get("type") != "FeatureCollection" or not isinstance(value.get("features"), list):
        raise InvalidRequest("geojson doit etre une FeatureCollection.")

    features = value["features"]

    if not features or len(features) > MAX_FEATURES:
        raise InvalidRequest(f"geojson doit contenir de 1 a {MAX_FEATURES} objets.")

    positions: list[tuple[float, float]] = []
    kept = []

    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise InvalidRequest(f"geojson.features[{index}] doit etre un Feature.")

        geometry = feature.get("geometry")
        properties = feature.get("properties")

        if not isinstance(geometry, dict) or geometry.get("type") not in GEOMETRY_DEPTHS:
            raise InvalidRequest(f"geojson.features[{index}].geometry doit valoir {', '.join(GEOMETRY_DEPTHS)}.")

        if properties is not None and not isinstance(properties, dict):
            raise InvalidRequest(f"geojson.features[{index}].properties doit etre un objet.")

        if not _collect_positions(geometry.get("coordinates"), GEOMETRY_DEPTHS[geometry["type"]], positions):
            raise InvalidRequest(f"geojson.features[{index}] a des coordonnees hors WGS 84 (longitude, latitude en degres).")

        kept.append({"type": "Feature", "geometry": {"type": geometry["type"], "coordinates": geometry["coordinates"]}, "properties": properties or {}})

    document = {"type": "FeatureCollection", "features": kept}

    if len(json.dumps(document, separators=(",", ":"))) > MAX_GEOJSON_BYTES:
        raise InvalidRequest(f"geojson ne doit pas depasser {MAX_GEOJSON_BYTES // (1024 * 1024)} Mo.")

    longitudes = [longitude for longitude, _ in positions]
    latitudes = [latitude for _, latitude in positions]
    return document, (min(longitudes), min(latitudes), max(longitudes), max(latitudes))


def _collect_positions(coordinates: Any, depth: int, positions: list[tuple[float, float]]) -> bool:
    if not isinstance(coordinates, list):
        return False

    if depth == 0:
        if len(coordinates) < 2 or not all(_is_number(value) for value in coordinates[:3]):
            return False

        longitude, latitude = coordinates[0], coordinates[1]

        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            return False

        positions.append((longitude, latitude))
        return True

    return bool(coordinates) and all(_collect_positions(child, depth - 1, positions) for child in coordinates)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


# Style d'une couche fichier. Chaque réglage est facultatif : absent, le front applique le sien.
def layer_style(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidRequest("style doit etre un objet.")

    known = {"color", "labelField"} | {name for name, _, _ in STYLE_NUMBERS}
    unknown = [name for name in value if name not in known]

    if unknown:
        raise InvalidRequest(f"Reglage de style inconnu : {', '.join(unknown)}.")

    style: dict[str, Any] = {}
    color = value.get("color")

    if color is not None:
        if not isinstance(color, str) or not HEX_COLOR.fullmatch(color):
            raise InvalidRequest("style.color doit etre une couleur #rrggbb.")
        style["color"] = color.lower()

    for name, minimum, maximum in STYLE_NUMBERS:
        number = value.get(name)

        if number is None:
            continue

        if not _is_number(number) or not minimum <= number <= maximum:
            raise InvalidRequest(f"style.{name} doit etre un nombre de {minimum} a {maximum}.")

        style[name] = number

    label_field = value.get("labelField")

    if label_field is not None:
        if not isinstance(label_field, str) or not label_field or len(label_field) > MAX_LABEL_FIELD_LENGTH:
            raise InvalidRequest(f"style.labelField doit etre un texte de 1 a {MAX_LABEL_FIELD_LENGTH} caracteres, ou null.")
        style["labelField"] = label_field

    return style


# Service de l'agent dans Azure AD (attribut « department » de Microsoft Graph, ex. « 44EN », « GFDT »),
# lu par le front à chaque connexion et gardé tel quel dans users.department. Vide = inconnu.
MAX_DEPARTMENT_LENGTH = 100


def department(value: Any) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str) or len(value.strip()) > MAX_DEPARTMENT_LENGTH:
        raise InvalidRequest(f"department doit etre un texte de {MAX_DEPARTMENT_LENGTH} caracteres au plus, ou null.")

    return value.strip() or None
