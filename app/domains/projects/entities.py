# Objets métier des affaires : affaire, sondage, chantier, décompte des sondages et statut de
# géolocalisation. Règles reprises du domaine Affaires du back Symfony (Project, Survey,
# GeolocationClassifier, SurveyName, ProjectSearchCriteria…), avec les mêmes messages d'erreur.

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.core.errors import InvalidRequest

# Types d'affaire dont la géolocalisation se juge sur les sondages, pas sur la position de l'affaire.
SURVEY_DRIVEN_TYPE_IDS = (1, 2)
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1000
MAX_STATUS_PROJECTS = 1000
PROJECT_SURVEYS_LIMIT = 150
SURVEY_NAME = re.compile(r"[^\W_][\w .\-]{0,39}")


@dataclass(frozen=True)
class Coordinates:
    longitude: float
    latitude: float


# Coordonnées fournies par l'agent : hors bornes, elles sont refusées (400).
def coordinates_of(longitude: float, latitude: float) -> Coordinates:
    if not -180 <= longitude <= 180:
        raise InvalidRequest(f"Longitude hors bornes : {longitude:f}")

    if not -90 <= latitude <= 90:
        raise InvalidRequest(f"Latitude hors bornes : {latitude:f}")

    return Coordinates(longitude, latitude)


# Position envoyée par l'ancien contrat : (0, 0) ou une latitude nulle veulent dire « pas de position ».
def coordinates_from_geolocation(longitude: float | None, latitude: float | None) -> Coordinates | None:
    if longitude is None or latitude is None or latitude == 0:
        return None

    return coordinates_of(longitude, latitude)


# Position lue en base : une valeur hors bornes (donnée ancienne) est ignorée plutôt que renvoyée.
def stored_coordinates(longitude: float | None, latitude: float | None) -> Coordinates | None:
    if longitude is None or latitude is None or not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        return None

    return Coordinates(longitude, latitude)


# Position telle que saisie à l'origine (avec son système géodésique), conservée pour l'affichage.
@dataclass(frozen=True)
class EnteredPosition:
    longitude: float | None = None
    latitude: float | None = None
    geodetic_system: str | None = None


@dataclass(frozen=True)
class Project:
    id: str
    name: str | None = None
    coordinates: Coordinates | None = None
    no_geo_reason_id: int | None = None
    type_id: int | None = None
    city: str | None = None
    city_agency: str | None = None
    code_metier: str | None = None
    client: str | None = None
    uuid: str | None = None
    externe_id: str | None = None
    url_id: str | None = None
    altitude: float | None = None
    is_doc_ged: bool = False
    is_doc_ged_updated_by: str | None = None
    is_doc_ged_updated_at: datetime | None = None
    entered_position: EnteredPosition = field(default_factory=EnteredPosition)
    user_email: str | None = None
    updated_at: datetime | None = None

    # Le motif 0 vaut une absence de motif (donnée héritée de l'ancien back Go).
    @property
    def has_no_geo_reason(self) -> bool:
        return self.no_geo_reason_id not in (None, 0)

    @property
    def is_survey_driven(self) -> bool:
        return self.type_id in SURVEY_DRIVEN_TYPE_IDS


@dataclass(frozen=True)
class Survey:
    id: str
    site_id: str
    coordinates: Coordinates | None = None
    no_geo_reason_id: int | None = None
    city: str | None = None
    altitude: float | None = None
    depth_min: float | None = None
    depth_max: float | None = None
    entered_position: EnteredPosition = field(default_factory=EnteredPosition)
    updated_at: datetime | None = None


@dataclass(frozen=True)
class Site:
    id: str
    coordinates: Coordinates | None


# Nombre de sondages d'une affaire, et parmi eux ceux qui sont traités (positionnés, ou marqués
# non géolocalisables).
@dataclass(frozen=True)
class SurveyTally:
    total: int = 0
    geolocated: int = 0

    def __post_init__(self) -> None:
        if self.total < 0 or self.geolocated < 0:
            raise ValueError("Un decompte de sondages ne peut pas etre negatif.")

        if self.geolocated > self.total:
            raise ValueError(f"Incoherence : {self.geolocated} sondages geolocalises pour {self.total} sondages au total.")

    @property
    def is_empty(self) -> bool:
        return self.total == 0

    @property
    def is_fully_geolocated(self) -> bool:
        return self.total > 0 and self.total == self.geolocated

    @property
    def has_pending(self) -> bool:
        return self.total > self.geolocated


class GeolocationStatus(Enum):
    GEOLOCATED = "geolocated"
    TO_GEOLOCATE = "to_geolocate"
    SURVEYS_TO_GEOLOCATE = "surveys_to_geolocate"
    EXCLUDED = "excluded"
    UNCLASSIFIED = "unclassified"


# Statut de géolocalisation d'une affaire. Doit rester d'accord avec le SQL des filtres
# (queries.geolocation_having) : les tests le vérifient sur une base réelle.
def classify(project: Project, tally: SurveyTally) -> GeolocationStatus:
    has_position = project.coordinates is not None

    if project.has_no_geo_reason:
        return GeolocationStatus.EXCLUDED

    if project.is_survey_driven:
        if tally.is_fully_geolocated:
            return GeolocationStatus.GEOLOCATED
    elif has_position and (tally.is_empty or tally.is_fully_geolocated):
        return GeolocationStatus.GEOLOCATED

    if not has_position and not project.is_survey_driven:
        return GeolocationStatus.TO_GEOLOCATE

    if tally.has_pending:
        return GeolocationStatus.SURVEYS_TO_GEOLOCATE

    return GeolocationStatus.UNCLASSIFIED


# Filtre « selectedGeo » de l'écran Projets : 4 regroupe les affaires exclues et non classées.
class GeolocationFilter(Enum):
    GEOLOCATED = "1"
    TO_GEOLOCATE = "2"
    SURVEYS_TO_GEOLOCATE = "3"
    IMPOSSIBLE = "4"

    def matches(self, status: GeolocationStatus) -> bool:
        return status in {
            GeolocationFilter.GEOLOCATED: {GeolocationStatus.GEOLOCATED},
            GeolocationFilter.TO_GEOLOCATE: {GeolocationStatus.TO_GEOLOCATE},
            GeolocationFilter.SURVEYS_TO_GEOLOCATE: {GeolocationStatus.SURVEYS_TO_GEOLOCATE},
            GeolocationFilter.IMPOSSIBLE: {GeolocationStatus.EXCLUDED, GeolocationStatus.UNCLASSIFIED},
        }[self]


class SurveyPresenceFilter(Enum):
    WITH_SURVEYS = "1"
    WITHOUT_SURVEYS = "2"


class GedFilter(Enum):
    WITH_DOCUMENTS = "1"
    WITHOUT_DOCUMENTS = "2"


# Colonnes de tri proposées par l'écran Projets (liste fermée : jamais de SQL venu de la requête).
SORT_COLUMNS = {
    "number": None,
    "name": "p.name",
    "city": "p.city",
    "client": "p.client",
    "agency": "p.city_agency",
    "businessCode": "p.code_metier",
}


@dataclass(frozen=True)
class SearchCriteria:
    project_id: str | None = None
    name: str | None = None
    city: str | None = None
    city_agency: str | None = None
    code_metier: str | None = None
    client: str | None = None
    geolocation_filter: GeolocationFilter | None = None
    survey_filter: SurveyPresenceFilter | None = None
    ged_filter: GedFilter | None = None
    offset: int = 0
    limit: int = DEFAULT_PAGE_SIZE
    count_total: bool = True
    sort: str = "number"
    descending: bool = False


# Lit les paramètres de GET /projects comme le faisait Symfony : vides, « undefined » et « null »
# ne filtrent rien ; un code de filtre inconnu est ignoré ; un tri inconnu est refusé (400).
def search_criteria(query: dict[str, str]) -> SearchCriteria:
    sort = _present(query.get("sort"))
    order = _present(query.get("order"))

    if sort is not None and sort not in SORT_COLUMNS:
        raise InvalidRequest(f"sort : colonne inconnue « {sort} » (attendu : {', '.join(SORT_COLUMNS)}).")

    if order is not None and order not in ("asc", "desc"):
        raise InvalidRequest(f"order : sens inconnu « {order} » (attendu : asc, desc).")

    return SearchCriteria(
        project_id=_present(query.get("projectId")),
        name=_present(query.get("name")),
        city=_present(query.get("city")),
        city_agency=_present(query.get("cityAgency")),
        code_metier=_present(query.get("codeMetier")),
        client=_present(query.get("client")),
        geolocation_filter=_choice(GeolocationFilter, query.get("selectedGeo")),
        survey_filter=_choice(SurveyPresenceFilter, query.get("selectedSurvey")),
        ged_filter=_choice(GedFilter, query.get("selectedGeds")),
        offset=max(0, php_int(query.get("offset", 0))),
        limit=min(MAX_PAGE_SIZE, max(1, php_int(query.get("limit", DEFAULT_PAGE_SIZE)))),
        count_total=str(query.get("withoutPaginate", "0")) != "1",
        sort=sort or "number",
        descending=order == "desc",
    )


def _present(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None

    value = value.strip()
    return None if value in ("", "undefined", "null") else value


def _choice(enum: type[Enum], value: str | None):
    code = _present(value)
    return next((choice for choice in enum if choice.value == code), None)


# Un nombre JSON : en Python, True et False sont aussi des entiers, d'où l'exclusion explicite.
def is_number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


# Conversion d'une valeur en entier comme le cast (int) de PHP : « 12abc » vaut 12, « abc » vaut 0.
def php_int(value) -> int:
    if isinstance(value, bool):
        return int(value)

    if isinstance(value, int | float):
        return int(value) if math.isfinite(value) else 0

    match = re.match(r"\s*([+-]?\d+)", str(value))
    return int(match.group(1)) if match else 0


# Conversion d'une valeur en flottant comme le cast (float) de PHP : un texte non numérique vaut 0.
def php_float(value) -> float:
    if isinstance(value, bool | int | float):
        return float(value)

    match = re.match(r"\s*([+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?)", str(value))
    return float(match.group(1)) if match else 0.0


# Nom d'un nouveau sondage : 1 à 40 lettres, chiffres, espaces, « _ », « . » ou « - », sans
# commencer par un séparateur. L'identifiant du sondage est « <n° d'affaire>_<nom> ».
def survey_name(value: str) -> str:
    name = value.strip()

    if not SURVEY_NAME.fullmatch(name):
        raise InvalidRequest(f"Nom de sondage invalide : « {name} ».")

    return name


# Chantier le plus proche d'une position (distance approchée, suffisante à l'échelle d'une affaire).
# Un chantier sans position n'est retenu que si aucun n'en a.
def nearest_site(sites: list[Site], coordinates: Coordinates) -> Site | None:
    nearest, nearest_distance = None, math.inf

    for site in sites:
        distance = _squared_distance(site.coordinates, coordinates)

        if nearest is None or distance < nearest_distance:
            nearest, nearest_distance = site, distance

    return nearest


def _squared_distance(origin: Coordinates | None, target: Coordinates) -> float:
    if origin is None:
        return math.inf

    longitude_scale = math.cos(math.radians((origin.latitude + target.latitude) / 2))
    dx = (origin.longitude - target.longitude) * longitude_scale
    dy = origin.latitude - target.latitude
    return dx * dx + dy * dy
