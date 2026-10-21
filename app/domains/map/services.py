# Logique métier du domaine map : appelé par routes.py, appelle queries.py.
# Simple aujourd'hui (lire et renvoyer) ; accueillera un éventuel regroupement des points ou un tri.

from collections.abc import Sequence
from sqlalchemy import Row
from app.domains.map import queries
from app.domains.map.entities import Points
from app.domains.map.schemas import Bounds

# Les deux premières colonnes de chaque requête, qui ne sont pas des propriétés.
POSITION_COLUMNS = ("longitude", "latitude")


def sites_in_area(bounds: Bounds, with_details: bool) -> Points:
    return _points(queries.sites_in_area(bounds, with_details))


def surveys_in_area(bounds: Bounds, with_details: bool) -> Points:
    return _points(queries.surveys_in_area(bounds, with_details))


# Enveloppe le résultat de la base dans une entité Points : les noms des colonnes après
# longitude et latitude deviennent les noms des propriétés ; les lignes sont gardées telles quelles.
def _points(result: tuple[list[str], Sequence[Row]]) -> Points:
    columns, rows = result
    return Points(property_names=columns[len(POSITION_COLUMNS):], rows=rows)
