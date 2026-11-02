# Logique métier du cadastre du Luxembourg : appelé par routes.py, appelle sources.py.

from app.domains.luxembourg.land_registry import sources
from app.domains.luxembourg.land_registry.entities import Parcel, Zoning

SECTION_LEVEL = "Section"
MUNICIPALITY_LEVEL = "Cadastral Municipality"
# Le découpage change rarement et compte quelques centaines de sections : il est gardé en mémoire, par
# référence de section, pour ne plus interroger le service qu'une fois par parcelle survolée ensuite.
_zonings: dict[str, Zoning] = {}


def _zoning_of(features: list[dict]) -> Zoning:
    by_level = {(feature.get("properties") or {}).get("level_name"): feature.get("properties") or {} for feature in features}
    section = by_level.get(SECTION_LEVEL, {})
    municipality = by_level.get(MUNICIPALITY_LEVEL, {})
    section_reference = section.get("national_cadastral_zoning_reference")
    municipality_reference = municipality.get("national_cadastral_zoning_reference") or ""
    # « 075F » dans la commune « 075 » : la section est ce qui suit le code de la commune.
    section_code = section_reference[len(municipality_reference) :] if section_reference else None
    return Zoning(municipality=municipality.get("label"), section=section_code or None, section_name=section.get("label"))


# Référence de la section d'une parcelle : « …/LIMADM_SECTIONS.75F » → « LIMADM_SECTIONS.75F ».
def _section_key(properties: dict) -> str | None:
    zoning = properties.get("zoning")
    return zoning.rsplit("/", 1)[-1] if isinstance(zoning, str) and zoning else None


def _zoning_at(longitude: float, latitude: float, key: str | None) -> Zoning:
    if key is not None and key in _zonings:
        return _zonings[key]
    zoning = _zoning_of(sources.zoning_features_at(longitude, latitude))
    if key is not None:
        _zonings[key] = zoning
    return zoning


# Renvoie la parcelle qui contient ce point (clic ou survol sur la carte), ou None hors du cadastre.
def parcel_at(longitude: float, latitude: float) -> Parcel | None:
    for feature in sources.parcel_features_at(longitude, latitude):
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}
        reference, number = properties.get("national_cadastral_reference"), properties.get("label")
        if geometry.get("type") in ("Polygon", "MultiPolygon") and reference and number:
            area = properties.get("area")
            return Parcel(
                reference=str(reference),
                number=str(number),
                area_m2=float(area) if isinstance(area, (int, float)) else None,
                geometry=geometry,
                zoning=_zoning_at(longitude, latitude, _section_key(properties)),
            )
    return None
