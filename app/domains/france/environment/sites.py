# Sites pollués ou à risques dans le rayon d'un point ou de parcelles, lus dans les tables de sites du catalogue
# des couches : casias_sites (migration 0048), basol_sites (0051), sis_sites (0052) et icpe_sites (0055),
# importées depuis CASIAS.gpkg, BASOL.gpkg, SIS.gpkg et ICPE.gpkg par app/domains/layer_catalog/casias.py,
# basol.py, sis.py et icpe.py. Les tableaux de l'enquête lisent ainsi
# les mêmes sites que les couches, sans l'API Solscore v2 : sa route /fr/basol ne rend ni le code SSP ni la fiche
# Géorisques, et ses routes dépendent d'un second exemplaire des fichiers, chargé à son démarrage (ADR-0071 et
# ADR-0072 du front).
#
# Réponse au format de /fr/casias de l'API Solscore v2 : un site par code (SiteTable.key : code_metier, code_aiot
# pour les ICPE) (son emprise s'il en a une, sinon son
# point), trié par distance croissante ; distance_m est la distance au lieu, sur l'ellipsoïde, 0 si le site le
# touche. La géométrie rendue est un point sur le site, pour ne pas renvoyer des emprises de plusieurs centaines
# de Ko.

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from app.domains.france.schemas import RadiusSearch


@dataclass(frozen=True)
class SiteTable:
    table: str
    properties: tuple[str, ...]
    key: str = "code_metier"


CASIAS = SiteTable(
    table="casias_sites",
    properties=(
        "code_metier", "nom_inventaire", "code_inventaire", "nom_etablissement", "adresse", "code_insee", "nom_commune",
        "etat_activite", "nature_localisation", "fiche_risque",
    ),
)

BASOL = SiteTable(
    table="basol_sites",
    properties=(
        "code_metier", "url_fiche", "nom_etablissement", "adresse", "code_postal", "nom_commune", "statut_instruction",
        "date_debut", "date_fin", "date_maj",
    ),
)

SIS = SiteTable(
    table="sis_sites",
    properties=(
        "code_metier", "url_fiche", "id_inventaire_classification", "nom_etablissement", "adresse", "code_postal",
        "code_insee", "nom_commune", "date_ap",
    ),
)

ICPE = SiteTable(
    table="icpe_sites",
    properties=(
        "code_aiot", "url_fiche", "raison_sociale", "adresse", "code_postal", "commune", "activite_principale",
        "seveso", "etat_activite", "regime_vig", "legende",
    ),
    key="code_aiot",
)


# Le lieu en EPSG:4326 ; l'emprise de recherche en EPSG:3857 (index spatial de la table) est élargie du rayon
# divisé par le cosinus de la latitude, l'échelle du Web Mercator, avant le calcul exact des distances.
def _query(sites: SiteTable) -> str:
    return f"""
        WITH place AS (
            SELECT geometry, ST_Expand(ST_Transform(geometry, 3857), :radius / cos(radians(ST_Y(ST_Centroid(geometry))))) AS box
            FROM (SELECT ST_SetSRID(ST_GeomFromGeoJSON(:place), 4326) AS geometry) given
        ),
        sites AS (
            SELECT DISTINCT ON (s.{sites.key}) {", ".join(f"s.{column}" for column in sites.properties)}, s.shape,
                   ST_Transform(s.geometry, 4326) AS geometry
            FROM {sites.table} s, place
            WHERE s.geometry && place.box
            ORDER BY s.{sites.key}, s.shape = 'polygon' DESC
        )
        SELECT {", ".join(sites.properties)}, CASE shape WHEN 'polygon' THEN 'polygone' ELSE 'point' END AS type_geometrie,
               round(ST_Distance(sites.geometry::geography, place.geometry::geography))::int AS distance_m,
               ST_AsGeoJSON(ST_PointOnSurface(sites.geometry), 6) AS marker
        FROM sites, place
        WHERE ST_DWithin(sites.geometry::geography, place.geometry::geography, :radius)
        ORDER BY distance_m, {sites.key}
    """


def _place(search: RadiusSearch) -> dict[str, Any]:
    if search.parcelles:
        rings = [outline if outline[0] == outline[-1] else [*outline, outline[0]] for outline in search.parcelles]
        return {"type": "MultiPolygon", "coordinates": [[ring] for ring in rings]}
    return {"type": "Point", "coordinates": [search.lon, search.lat]}


def sites_within(connection: Connection, sites: SiteTable, search: RadiusSearch) -> dict[str, Any]:
    rows = connection.execute(text(_query(sites)), {"place": json.dumps(_place(search)), "radius": search.rayon_m}).mappings().all()
    features = [
        {"type": "Feature", "geometry": json.loads(row["marker"]), "properties": {key: value for key, value in row.items() if key != "marker"}}
        for row in rows
    ]
    return {
        "mode_recherche": "parcelles" if search.parcelles else "point",
        "nombre_total": len(features),
        "rayon_recherche": search.rayon_m,
        "data": {"type": "FeatureCollection", "features": features},
    }
