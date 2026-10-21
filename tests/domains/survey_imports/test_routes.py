from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.core.auth import current_user
from app.domains.survey_imports import services
from app.main import app

ROUTE = "/survey-imports/workbook"
# Classeur .xls de test, produit par fixtures/make_sondages_xls.py.
LEGACY_WORKBOOK = Path(__file__).parent / "fixtures" / "sondages.xls"


@pytest.fixture
def client():
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def workbook_bytes(sheets: dict[str, list[list[object]]]) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        worksheet = workbook.create_sheet(name)
        for row in rows:
            worksheet.append(row)
    content = BytesIO()
    workbook.save(content)
    return content.getvalue()


def upload(client, content: bytes, name: str = "sondages.xlsx"):
    return client.post(ROUTE, files={"file": (name, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})


def test_every_sheet_is_returned_in_order_with_cells_as_text(client):
    content = workbook_bytes(
        {
            "Sondages": [
                ["Nom", "Début", "Latitude", "Longitude", "Élévation", "Niveau d'eau"],
                ["SP1", date(2020, 1, 24), 47.443257021, -0.543013886, 31.92, None],
                ["RG1", datetime(2020, 1, 27, 9, 30), 47.443482615, -0.542854434, 32, 0.00001],
            ],
            "Projet": [["Référence", "PR.GFIT.26.0004"]],
        }
    )

    response = upload(client, content)

    assert response.status_code == 200
    sheets = response.json()["sheets"]
    assert [sheet["name"] for sheet in sheets] == ["Sondages", "Projet"]
    assert sheets[0]["rows"] == [
        ["Nom", "Début", "Latitude", "Longitude", "Élévation", "Niveau d'eau"],
        ["SP1", "24/01/2020", "47.443257021", "-0.543013886", "31.92"],
        ["RG1", "27/01/2020 09:30", "47.443482615", "-0.542854434", "32", "0.00001"],
    ]
    assert sheets[0]["truncated"] is False
    assert sheets[1]["rows"] == [["Référence", "PR.GFIT.26.0004"]]


def test_a_legacy_xls_workbook_is_read_like_an_xlsx(client):
    response = upload(client, LEGACY_WORKBOOK.read_bytes(), "Sondages OUDON.XLS")

    assert response.status_code == 200
    sheets = response.json()["sheets"]
    assert [sheet["name"] for sheet in sheets] == ["Sondages", "Projet"]
    assert sheets[0]["rows"] == [
        ["Nom", "Début", "Latitude", "Longitude", "Élévation", "Niveau d'eau", "Validé"],
        ["SP1", "24/01/2020", "47.443257021", "-0.543013886", "31.92", "", "VRAI"],
        ["RG1", "27/01/2020 09:30", "47.443482615", "-0.542854434", "32", "0.00001"],
    ]
    assert sheets[1]["rows"] == [["Référence", "PR.GFIT.26.0004"]]


def test_a_long_legacy_sheet_is_truncated_and_flagged(client, monkeypatch):
    monkeypatch.setattr(services, "MAX_ROWS", 2)

    sheet = upload(client, LEGACY_WORKBOOK.read_bytes(), "sondages.xls").json()["sheets"][0]

    assert len(sheet["rows"]) == 2
    assert sheet["truncated"] is True


def test_blank_cells_inside_a_row_are_kept_and_trailing_blank_rows_dropped(client):
    content = workbook_bytes({"Forage": [["SP1", None, "2.5"], [None, None], [None]]})

    assert upload(client, content).json()["sheets"][0]["rows"] == [["SP1", "", "2.5"]]


def test_a_long_sheet_is_truncated_and_flagged(client, monkeypatch):
    monkeypatch.setattr(services, "MAX_ROWS", 3)
    content = workbook_bytes({"CPT": [["Sondage", "Prof."], *[["CPT1", depth] for depth in range(10)]]})

    sheet = upload(client, content).json()["sheets"][0]

    assert len(sheet["rows"]) == 3
    assert sheet["truncated"] is True


@pytest.mark.parametrize(
    "name, content",
    [
        ("sondages.xls", b"\xd0\xcf\x11\xe0 ancien format abime"),
        ("sondages.xls", b"pas un classeur"),
        ("sondages.xlsx", b"pas un classeur"),
        ("sondages.xlsx", b""),
        ("sondages.csv", b"Nom;Latitude"),
    ],
)
def test_an_unreadable_or_unsupported_file_is_refused(client, name, content):
    response = upload(client, content, name)

    assert response.status_code == 400
    assert response.json()["errors"]


def test_a_file_over_the_limit_is_refused(client, monkeypatch):
    monkeypatch.setattr(services, "MAX_WORKBOOK_BYTES", 100)

    assert upload(client, workbook_bytes({"Sondages": [["Nom"]]})).status_code == 400


def test_a_request_without_file_is_refused(client):
    assert client.post(ROUTE).status_code == 400


def test_a_request_without_token_is_refused(client):
    app.dependency_overrides.clear()

    assert upload(client, workbook_bytes({"Sondages": [["Nom"]]})).status_code == 401
