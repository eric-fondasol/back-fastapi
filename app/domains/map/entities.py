# Objets métier du domaine map, manipulés par services.py et convertis en GeoJSON par routes.py.

from collections.abc import Sequence
from dataclasses import dataclass
from sqlalchemy import Row


# frozen=True : l'objet ne peut pas être modifié après sa création.
@dataclass(frozen=True)
class Points:
    """Points of the map: each row starts with longitude and latitude, followed by the properties."""

    # Noms des propriétés, dans l'ordre des colonnes qui suivent longitude et latitude.
    property_names: list[str]
    # Lignes telles que renvoyées par la base, sans les convertir en dictionnaires (plus rapide).
    rows: Sequence[Row]
