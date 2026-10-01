import os
import tempfile

os.environ["LOG_DIR"] = tempfile.mkdtemp(prefix="solscore-logs-")

import pytest  # noqa: E402

from app.core import audit  # noqa: E402


@pytest.fixture(autouse=True)
def audit_entries(monkeypatch):
    entries = []
    monkeypatch.setattr(audit, "save", entries.append)
    return entries
