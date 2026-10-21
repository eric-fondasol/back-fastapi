import os
import tempfile

os.environ["LOG_DIR"] = tempfile.mkdtemp(prefix="solscore-logs-")

from app.core.config import config  # noqa: E402

config.db_refonte_name = config.db_refonte_test_name

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.core import audit, warmup  # noqa: E402
from app.database.connection import refonte_engine, refonte_url  # noqa: E402

KEPT_TABLES = {"alembic_version", "spatial_ref_sys"}


@pytest.fixture(autouse=True)
def audit_entries(monkeypatch):
    entries = []
    monkeypatch.setattr(audit, "save", entries.append)
    return entries


@pytest.fixture(autouse=True)
def no_warm_up(monkeypatch):
    monkeypatch.setattr(warmup, "warm_up", lambda: None)


@pytest.fixture(scope="session")
def refonte_schema():
    name = config.db_refonte_name

    if not name.endswith("_test"):
        raise RuntimeError(f"Tests refused on {name}: the business test database name must end with _test")

    with create_engine(refonte_url("postgres"), isolation_level="AUTOCOMMIT").connect() as server:
        if server.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}).scalar() is None:
            server.execute(text(f'CREATE DATABASE "{name}"'))

    with refonte_engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    command.upgrade(AlembicConfig("alembic.ini"), "head")


@pytest.fixture
def refonte_database(refonte_schema):
    with refonte_engine.begin() as connection:
        tables = connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars()
        emptied = ", ".join(f'"{table}"' for table in tables if table not in KEPT_TABLES)
        connection.execute(text(f"TRUNCATE {emptied} RESTART IDENTITY CASCADE"))

    return refonte_engine
