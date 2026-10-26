# SQL du domaine map : lit les sites et les sondages dans une emprise (rectangle de carte).

from collections.abc import Sequence
from sqlalchemy import Row
from app.database.connection import fetch_rows
from app.domains.map.schemas import Bounds

# Source des sites : chaque site est rattaché à une affaire ; les sites sans position sont exclus.
SITES = """
    FROM public.site s
    JOIN public.affaire a ON a.id = s.affaire_id
    WHERE s.latitude IS NOT NULL
      AND s.longitude IS NOT NULL
"""

# Propriétés ajoutées pour les routes « …Details ». Chaque alias (AS …) est le nom de la propriété
# dans le JSON renvoyé au front. La virgule de tête suit la colonne latitude dans le SELECT.
SITE_PROPERTIES = """,
    s.uuid::text AS uuid,
    a.id::text AS affaire_id,
    a.numero AS affaire_numero,
    a.nom AS affaire_nom
"""

# Source des sondages : seuls ceux qui ont une position.
SURVEYS = """
    FROM public.sondage
    WHERE localisation_longitude_xwgs84 IS NOT NULL
      AND localisation_latitude_ywgs84 IS NOT NULL
"""

# COALESCE : les indicateurs de nature valent toujours true ou false pour le front, jamais null.
# Le front en tire le symbole du sondage (pressiométrique, pénétrométrique, autre).
SURVEY_PROPERTIES = """,
    id::text AS id,
    nom,
    site_uuid::text AS site_uuid,
    COALESCE(has_mesure_pressiometrique, false) AS has_mesure_pressiometrique,
    COALESCE(has_essai_penetro_dynamique, false) AS has_essai_penetro_dynamique,
    COALESCE(has_lithologie, false) AS has_lithologie
"""


# Assemble une requête de points. Les arguments sont uniquement des morceaux de SQL écrits dans ce
# fichier ; les valeurs du front passent par les paramètres :minLng, :maxLng…, jamais par le f-string.
def points_sql(longitude: str, latitude: str, properties: str, source: str) -> str:
    # Contrainte : longitude puis latitude doivent rester les deux premières colonnes,
    # services.py et routes.py s'appuient sur leur position.
    # round(…, 6) : 6 décimales, environ 11 cm, suffisant pour la carte et plus léger à transférer.
    # CAST(… AS numeric) : compare dans le même type que les colonnes.
    return f"""
        SELECT round({longitude}, 6)::float8 AS longitude,
               round({latitude}, 6)::float8 AS latitude
               {properties}
        {source}
          AND {longitude} BETWEEN CAST(:minLng AS numeric) AND CAST(:maxLng AS numeric)
          AND {latitude} BETWEEN CAST(:minLat AS numeric) AND CAST(:maxLat AS numeric)
    """


# Les quatre requêtes sont assemblées une seule fois, au chargement du module.
SITES_SQL = points_sql("s.longitude", "s.latitude", "", SITES)
SITES_WITH_DETAILS_SQL = points_sql("s.longitude", "s.latitude", SITE_PROPERTIES, SITES)

SURVEYS_SQL = points_sql("localisation_longitude_xwgs84", "localisation_latitude_ywgs84", "", SURVEYS)
SURVEYS_WITH_DETAILS_SQL = points_sql(
    "localisation_longitude_xwgs84", "localisation_latitude_ywgs84", SURVEY_PROPERTIES, SURVEYS
)


# bounds.model_dump() donne {"minLng": …, "maxLng": …, "minLat": …, "maxLat": …},
# passés comme paramètres :minLng… de la requête.
def sites_in_area(bounds: Bounds, with_details: bool) -> tuple[list[str], Sequence[Row]]:
    return fetch_rows(SITES_WITH_DETAILS_SQL if with_details else SITES_SQL, **bounds.model_dump())


def surveys_in_area(bounds: Bounds, with_details: bool) -> tuple[list[str], Sequence[Row]]:
    return fetch_rows(SURVEYS_WITH_DETAILS_SQL if with_details else SURVEYS_SQL, **bounds.model_dump())
