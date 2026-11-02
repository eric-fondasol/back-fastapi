# Données du service externe : le WFS INSPIRE « Cadastral Parcels » du géoportail luxembourgeois (GeoServer,
# public, sans clé), qui diffuse le plan cadastral numérisé (PCN) de l'ACT : parcelles (numéro, superficie
# officielle, référence cadastrale) et découpage (communes cadastrales, sections).

import httpx

CADASTRAL_PARCELS_WFS_URL = "https://wms.inspire.geoportail.lu/geoserver/cp/wfs"
PARCEL_TYPE = "cp:CP.CadastralParcel"
ZONING_TYPE = "cp:CP.CadastralZoning"
# Au-delà de 10 s sans réponse, le service est considéré comme injoignable.
TIMEOUT_SECONDS = 10.0
# Champs utiles du découpage : sa géométrie (jusqu'à 15 Ko pour une commune) n'est pas demandée.
ZONING_FIELDS = "label,level_name,national_cadastral_zoning_reference"


# Erreur propre au domaine, traduite en 502 par routes.py. Le service n'a pas à connaître httpx.
class LandRegistryUnavailable(Exception):
    pass


# Filtre FES « intersecte ce point ». En EPSG:4326 au sens de l'URN, l'ordre des axes est latitude, longitude.
# Les deux nombres viennent d'un corps validé par schemas.py (flottants bornés) : rien d'autre n'est injecté.
def _point_filter(longitude: float, latitude: float) -> str:
    return (
        '<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0" xmlns:gml="http://www.opengis.net/gml/3.2">'
        "<fes:Intersects><fes:ValueReference>geometry</fes:ValueReference>"
        f'<gml:Point gml:id="p" srsName="urn:ogc:def:crs:EPSG::4326"><gml:pos>{latitude!r} {longitude!r}</gml:pos></gml:Point>'
        "</fes:Intersects></fes:Filter>"
    )


# Interroge le service et renvoie les objets trouvés, au format GeoJSON (liste de « features »).
def _features_at(type_name: str, longitude: float, latitude: float, **extra: str) -> list[dict]:
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": type_name,
        "OUTPUTFORMAT": "application/json",
        # Réponse en WGS 84, longitude puis latitude (GeoJSON), comme les cadastres France et Québec.
        "SRSNAME": "EPSG:4326",
        "FILTER": _point_filter(longitude, latitude),
        **extra,
    }
    try:
        response = httpx.get(CADASTRAL_PARCELS_WFS_URL, params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        body = response.json()
    # Erreur réseau, délai dépassé, statut d'erreur, ou réponse qui n'est pas du JSON (GeoServer répond par
    # une exception XML avec un statut 200 quand la requête lui déplaît : ValueError).
    except (httpx.HTTPError, ValueError) as error:
        raise LandRegistryUnavailable(str(error)) from error

    if not isinstance(body, dict) or not isinstance(body.get("features"), list):
        raise LandRegistryUnavailable(str(body)[:200])

    return body["features"]


# Parcelles qui contiennent ce point (clic ou survol sur la carte) : une seule en pratique.
def parcel_features_at(longitude: float, latitude: float) -> list[dict]:
    return _features_at(PARCEL_TYPE, longitude, latitude)


# Découpage qui contient ce point : la section (2ndOrder) et sa commune cadastrale (1stOrder), sans géométrie.
def zoning_features_at(longitude: float, latitude: float) -> list[dict]:
    return _features_at(ZONING_TYPE, longitude, latitude, PROPERTYNAME=ZONING_FIELDS)
