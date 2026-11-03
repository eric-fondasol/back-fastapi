import logging
import uuid
from datetime import datetime, timedelta

import orjson
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from app.core import audit
from app.core.audit import save as real_save
from app.core.config import config
from app.core.logger import DailyFileHandler
from app.main import app

DEV_TOKEN = "dev-token-" + "x" * 32
ATLANTIC = {"bounds": {"minLat": 40.0, "maxLat": 40.01, "minLng": -30.0, "maxLng": -29.99}}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "app_env", "dev")
    monkeypatch.setattr(config, "auth_dev_token", SecretStr(DEV_TOKEN))

    with TestClient(app) as test_client:
        yield test_client


def entry(**overrides):
    return {
        "created_at": datetime.now().astimezone(),
        "request_id": str(uuid.uuid4()),
        "username": "test@fondasol.fr",
        "action": "search_sites_by_area",
        "method": "POST",
        "path": "/searchSitesByArea",
        "status_code": 200,
        "duration_ms": 12,
        "ip_address": "127.0.0.1",
        "user_agent": "pytest",
        "details": orjson.dumps(ATLANTIC).decode(),
    } | overrides


def test_a_request_is_recorded_with_who_what_how_and_when(client, audit_entries):
    before = datetime.now().astimezone()
    response = client.post("/searchSitesByArea", json=ATLANTIC, headers={"Authorization": f"Bearer {DEV_TOKEN}"})

    assert response.status_code == 200
    assert len(audit_entries) == 1

    recorded = audit_entries[0]

    assert recorded["username"] == config.auth_dev_user
    assert recorded["action"] == "search_sites_by_area"
    assert recorded["method"] == "POST"
    assert recorded["path"] == "/searchSitesByArea"
    assert recorded["status_code"] == 200
    assert recorded["duration_ms"] >= 0
    assert recorded["ip_address"] == "testclient"
    details = orjson.loads(recorded["details"])

    assert details["body"] == ATLANTIC
    assert set(details["timings_ms"]) == {"auth", "db", "geojson"}
    assert all(duration >= 0 for duration in details["timings_ms"].values())
    assert sum(details["timings_ms"].values()) <= recorded["duration_ms"] + 2
    assert before <= recorded["created_at"] <= datetime.now().astimezone()
    assert response.headers["X-Request-ID"] == recorded["request_id"]


def test_a_rejected_request_is_recorded_as_anonymous(client, audit_entries):
    response = client.post("/searchSitesByArea", json=ATLANTIC)

    assert response.status_code == 401
    assert audit_entries[0]["username"] is None
    assert audit_entries[0]["status_code"] == 401


def test_an_invalid_request_is_recorded(client, audit_entries):
    response = client.post("/searchSitesByArea", json={}, headers={"Authorization": f"Bearer {DEV_TOKEN}"})

    assert response.status_code == 422
    assert audit_entries[0]["username"] == config.auth_dev_user
    assert audit_entries[0]["status_code"] == 422


@pytest.mark.parametrize("path", ["/api/health", "/docs", "/openapi.json", "/layer-catalog/fr-ign-scan25/tiles/12/2074/1409"])
def test_technical_routes_are_not_recorded(client, audit_entries, path):
    client.get(path)

    assert audit_entries == []


def test_an_unavailable_audit_database_does_not_break_the_request(client, monkeypatch):
    def unavailable(*_, **__):
        raise ConnectionError("audit database is down")

    monkeypatch.setattr(audit, "execute_usage_log", unavailable)
    monkeypatch.setattr(audit, "save", real_save)

    response = client.post("/searchSitesByArea", json=ATLANTIC, headers={"Authorization": f"Bearer {DEV_TOKEN}"})

    assert response.status_code == 200


def test_an_entry_is_saved_in_usage_logs(refonte_database):
    saved = entry()

    real_save(saved)

    with refonte_database.connect() as connection:
        row = connection.execute(
            text(
                "SELECT created_at, request_id::text AS request_id, username, action, method, path, status_code, "
                "duration_ms, ip_address, user_agent, details FROM usage_logs"
            )
        ).one()

    assert abs(row.created_at - saved["created_at"]) < timedelta(milliseconds=1)
    assert row.request_id == saved["request_id"]
    assert row.username == "test@fondasol.fr"
    assert row.action == "search_sites_by_area"
    assert row.method == "POST"
    assert row.path == "/searchSitesByArea"
    assert row.status_code == 200
    assert row.duration_ms == 12
    assert row.ip_address == "127.0.0.1"
    assert row.user_agent == "pytest"
    assert row.details == ATLANTIC


def test_an_entry_without_details_is_saved_with_an_empty_details(refonte_database):
    real_save(entry(details=None, username=None, action=None))

    with refonte_database.connect() as connection:
        row = connection.execute(text("SELECT username, action, details FROM usage_logs")).one()

    assert tuple(row) == (None, None, None)


def test_the_log_file_is_named_after_the_day_of_the_event(tmp_path):
    handler = DailyFileHandler(str(tmp_path))

    for day, message in (("2026-09-30", "first day"), ("2026-10-01", "next day")):
        record = logging.LogRecord("solscore", logging.INFO, __file__, 0, message, None, None)
        record.created = datetime.fromisoformat(f"{day} 12:00:00").timestamp()
        handler.emit(record)

    handler.close()

    assert (tmp_path / "2026-09-30.txt").read_text() == "first day\n"
    assert (tmp_path / "2026-10-01.txt").read_text() == "next day\n"
