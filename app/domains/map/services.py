from collections.abc import Sequence

from sqlalchemy import Row

from app.domains.map import queries
from app.domains.map.entities import Points
from app.domains.map.schemas import Bounds

POSITION_COLUMNS = ("longitude", "latitude")


def sites_in_area(bounds: Bounds, with_details: bool) -> Points:
    return _points(queries.sites_in_area(bounds, with_details))


def surveys_in_area(bounds: Bounds, with_details: bool) -> Points:
    return _points(queries.surveys_in_area(bounds, with_details))


def _points(result: tuple[list[str], Sequence[Row]]) -> Points:
    columns, rows = result
    return Points(property_names=columns[len(POSITION_COLUMNS):], rows=rows)
