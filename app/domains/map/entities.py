from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Row


@dataclass(frozen=True)
class Points:
    """Points of the map: each row starts with longitude and latitude, followed by the properties."""

    property_names: list[str]
    rows: Sequence[Row]
