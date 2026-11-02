import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

ALEMBIC = AlembicConfig("alembic.ini")

ENTRY = """
    INSERT INTO usage_logs (request_id, username, action, method, path, status_code, duration_ms, ip_address, user_agent, details)
    VALUES ('3f2b8c1e-6d4a-4b7e-9a1f-0c2d3e4f5a6b', 'dev@fondasol.fr', 'search_sites_by_area', 'POST', '/searchSitesByArea',
            :status_code, 312, '172.20.0.1', 'Mozilla/5.0', '{"query": {"zoom": "12"}}')
"""


def test_a_request_is_logged_with_the_same_columns_as_the_mysql_audit_log(schema_at):
    database = schema_at("0023")

    command.upgrade(ALEMBIC, "0024")

    with database.begin() as connection:
        connection.execute(text(ENTRY), {"status_code": 200})
        row = connection.execute(
            text(
                "SELECT id, created_at IS NOT NULL, request_id::text, username, action, method, path, status_code, "
                "duration_ms, ip_address, user_agent, details->'query'->>'zoom' FROM usage_logs"
            )
        ).one()

    assert row == (
        1, True, "3f2b8c1e-6d4a-4b7e-9a1f-0c2d3e4f5a6b", "dev@fondasol.fr", "search_sites_by_area", "POST",
        "/searchSitesByArea", 200, 312, "172.20.0.1", "Mozilla/5.0", "12",
    )


def test_a_negative_status_code_is_refused_like_an_unsigned_column(schema_at):
    database = schema_at("0024")

    with pytest.raises(IntegrityError), database.begin() as connection:
        connection.execute(text(ENTRY), {"status_code": -1})


def test_the_four_audit_log_indexes_are_created(schema_at):
    database = schema_at("0024")

    with database.connect() as connection:
        indexes = connection.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'usage_logs' ORDER BY indexname")).scalars().all()

    assert indexes == [
        "idx_usage_logs_action_created_at",
        "idx_usage_logs_created_at",
        "idx_usage_logs_request_id",
        "idx_usage_logs_username_created_at",
        "usage_logs_pkey",
    ]
