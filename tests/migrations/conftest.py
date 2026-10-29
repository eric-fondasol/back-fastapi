import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

from app.database.connection import refonte_engine

ALEMBIC = AlembicConfig("alembic.ini")


def _rebuild(revision: str) -> None:
    with refonte_engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    command.upgrade(ALEMBIC, revision)


# Base de test reconstruite jusqu'à une révision : les migrations du basculement v3 (0015 et
# suivantes) n'ont pas de retour arrière, on ne peut donc pas redescendre depuis head.
@pytest.fixture
def schema_at(refonte_schema):
    def at(revision: str):
        _rebuild(revision)
        return refonte_engine

    yield at
    _rebuild("head")
