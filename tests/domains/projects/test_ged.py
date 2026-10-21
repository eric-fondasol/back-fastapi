import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from app.core.auth import current_user
from app.core.config import config
from app.domains.projects import routes, sources
from app.main import app

GED = "https://vm-interne-ged.test/api"
GED_FILES = "https://vm-interne-ged.test/files"


@pytest.fixture(autouse=True)
def ged_configuration(monkeypatch):
    monkeypatch.setattr(config, "ged_base_uri", GED)
    monkeypatch.setattr(config, "ged_files_base_uri", GED_FILES)
    monkeypatch.setattr(config, "ged_username", "talend")
    monkeypatch.setattr(config, "ged_password", SecretStr("secret"))


def simulated_ged(monkeypatch, *answers):
    calls = []
    remaining = list(answers)

    def handler(request):
        calls.append(request)
        answer = remaining.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(sources, "transport", httpx.MockTransport(handler))
    return calls


def body(response):
    return b"".join(response.body)


def test_the_case_detail_is_relayed_with_its_useful_headers_only(monkeypatch):
    calls = simulated_ged(
        monkeypatch,
        httpx.Response(200, headers={"content-type": "application/json", "content-disposition": "inline", "server": "talend"}, content=b'{"ok":1}'),
    )

    response = sources.case_detail("IP.02.0222")

    assert (response.status_code, body(response), response.retried) == (200, b'{"ok":1}', False)
    assert response.headers == {"content-type": "application/json", "content-disposition": "inline", "content-length": "8"}
    assert str(calls[0].url) == f"{GED}/affaires/IP.02.0222"
    assert calls[0].headers["authorization"] == httpx.BasicAuth("talend", "secret")._auth_header


def test_a_network_failure_triggers_a_single_retry_then_succeeds(monkeypatch):
    calls = simulated_ged(monkeypatch, httpx.ReadTimeout("silence"), httpx.Response(200, content=b"{}"))

    response = sources.case_detail("IP.02.0222")

    assert (response.status_code, response.retried, len(calls)) == (200, True, 2)


def test_two_consecutive_network_failures_make_the_ged_unavailable(monkeypatch):
    simulated_ged(monkeypatch, httpx.ConnectError("refused"), httpx.ReadTimeout("silence"))

    with pytest.raises(sources.GedUnavailable):
        sources.case_detail("IP.02.0222")


def test_an_error_answer_from_the_ged_is_not_retried(monkeypatch):
    calls = simulated_ged(monkeypatch, httpx.Response(404, content=b"absent"))

    assert sources.case_detail("IP.02.0222").status_code == 404
    assert len(calls) == 1


def test_a_name_resolution_failure_is_not_retried(monkeypatch):
    calls = simulated_ged(monkeypatch, httpx.ConnectError("[Errno -2] Name or service not known"))

    with pytest.raises(sources.GedUnavailable):
        sources.case_detail("IP.02.0222")

    assert len(calls) == 1


def test_the_project_number_and_file_name_are_encoded_in_the_url(monkeypatch):
    calls = simulated_ged(monkeypatch, httpx.Response(200, content=b"%PDF"))

    sources.case_file("3EP 18/0016", "rapport final & annexes.pdf")

    assert str(calls[0].url) == f"{GED_FILES}/download/3EP%2018%2F0016?file=rapport+final+%26+annexes.pdf"


def test_the_case_detail_stops_after_three_seconds_of_silence_and_a_file_keeps_a_long_budget(monkeypatch):
    clients = []
    real_client = httpx.Client

    def recording_client(**options):
        clients.append(options["timeout"])
        return real_client(**options)

    simulated_ged(monkeypatch, httpx.Response(200), httpx.Response(200))
    monkeypatch.setattr(sources.httpx, "Client", recording_client)

    sources.case_detail("IP.02.0222")
    sources.case_file("IP.02.0222", "a.pdf")

    assert clients == [3.0, 60.0]


def test_an_unconfigured_ged_is_unavailable(monkeypatch):
    monkeypatch.setattr(config, "ged_base_uri", None)

    with pytest.raises(sources.GedUnavailable):
        sources.case_detail("IP.02.0222")


@pytest.fixture
def client(refonte_database):
    with refonte_database.begin() as connection:
        connection.execute(text("INSERT INTO projects (id, externe_id, is_doc_ged) VALUES ('EMA.04.0140', '39c6f5b1-c15b', true)"))

    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_the_case_detail_route_finds_the_project_by_its_ged_identifier(client, monkeypatch):
    calls = simulated_ged(monkeypatch, httpx.Response(200, headers={"content-type": "application/json"}, content=b'{"files":[]}'))

    response = client.get("/case-detail/39c6f5b1-c15b")

    assert (response.status_code, response.json()) == (200, {"files": []})
    assert str(calls[0].url) == f"{GED}/affaires/EMA.04.0140"


def test_an_unknown_ged_identifier_answers_not_found(client, monkeypatch):
    calls = simulated_ged(monkeypatch)

    assert client.get("/case-detail/inconnu").status_code == 404
    assert calls == []


def test_a_file_is_streamed_with_its_name(client, monkeypatch):
    simulated_ged(
        monkeypatch,
        httpx.Response(200, headers={"content-type": "application/pdf", "content-disposition": 'attachment; filename="r.pdf"'}, content=b"%PDF-1.7"),
    )

    response = client.get("/case-file/3EP%2018%2F0016?file=r.pdf")

    assert (response.status_code, response.content) == (200, b"%PDF-1.7")
    assert response.headers["content-disposition"] == 'attachment; filename="r.pdf"'


@pytest.mark.parametrize("path", ["/case-detail/39c6f5b1-c15b", "/case-file/EMA.04.0140?file=a.pdf"])
def test_an_unreachable_ged_answers_502_without_its_internal_address(client, monkeypatch, path):
    simulated_ged(monkeypatch, httpx.ConnectError("vm-interne-ged refused"), httpx.ConnectError("vm-interne-ged refused"))

    response = client.get(path)

    assert (response.status_code, response.json()) == (502, {"error": "ged injoignable"})
    assert "vm-interne-ged" not in response.text


def test_an_unconfigured_ged_is_explained_in_the_log(client, monkeypatch):
    errors = []
    monkeypatch.setattr(config, "ged_base_uri", None)
    monkeypatch.setattr(routes.logger, "error", lambda message, *args: errors.append(message % args))

    assert client.get("/case-detail/39c6f5b1-c15b").status_code == 502
    assert errors == ["GED indisponible : GED_BASE_URI absent de la configuration"]


def test_a_file_requested_without_name_is_refused(client, monkeypatch):
    calls = simulated_ged(monkeypatch)

    assert client.get("/case-file/EMA.04.0140").status_code == 400
    assert calls == []
