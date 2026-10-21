import ftplib
import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.auth import current_user
from app.core.config import config
from app.core.errors import InvalidRequest
from app.domains.reports import sources
from app.domains.reports.entities import archive_path
from app.main import app

REPOSITORY = {
    "/rapports/69gt/21/69gt.21.0142": {"b.pdf": b"rapport B", "a.pdf": b"rapport A", "illisible.pdf": None},
    "/rapports/31gt/22/31gt.22.0007": {"c.pdf": b"rapport C"},
}


class FakeFtp:
    instances = []

    def __init__(self, timeout):
        self.timeout, self.calls = timeout, []
        FakeFtp.instances.append(self)

    def connect(self, host, port):
        self.calls.append(("connect", host, port))

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def set_pasv(self, passive):
        self.calls.append(("pasv", passive))

    def nlst(self, path):
        if path not in REPOSITORY:
            raise ftplib.error_perm("550 No such directory")
        return [f"{path}/{name}" for name in REPOSITORY[path]] + [f"{path}/."]

    def retrbinary(self, command, callback):
        path, name = command.removeprefix("RETR ").rsplit("/", 1)
        content = REPOSITORY[path][name]
        if content is None:
            raise ftplib.error_perm("550 Permission denied")
        callback(content)

    def quit(self):
        self.calls.append(("quit",))


@pytest.fixture(autouse=True)
def ftp(monkeypatch):
    FakeFtp.instances = []
    monkeypatch.setattr(sources.ftplib, "FTP", FakeFtp)
    monkeypatch.setattr(config, "ftp_host", "ftp.test")
    monkeypatch.setattr(config, "ftp_port", 2121)
    monkeypatch.setattr(config, "ftp_username", "rapports")
    monkeypatch.setattr(config, "ftp_password", SecretStr("secret"))
    monkeypatch.setattr(config, "ftp_base_path", "/rapports/")


@pytest.fixture
def client():
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_the_path_follows_agency_year_folder():
    assert archive_path(" 69GT.21.0142 ").path == "69gt/21/69gt.21.0142"


@pytest.mark.parametrize("number", ["69GT21012", "69GT.21", "", ".21.0142", "../../etc.21.0142", "69GT.2/1.0142"])
def test_a_malformed_project_number_is_refused(number):
    with pytest.raises(InvalidRequest):
        archive_path(number)


def test_the_reports_of_several_projects_are_zipped_under_their_paths(client):
    response = client.get("/reports?projects=69GT.21.0142|31GT.22.0007|44GT.23.0001|")

    assert (response.status_code, response.headers["content-type"]) == (200, "application/zip")
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert sorted(archive.namelist()) == ["31gt/22/31gt.22.0007/c.pdf", "69gt/21/69gt.21.0142/a.pdf", "69gt/21/69gt.21.0142/b.pdf"]
    assert archive.read("69gt/21/69gt.21.0142/a.pdf") == b"rapport A"
    assert FakeFtp.instances[0].calls[:3] == [("connect", "ftp.test", 2121), ("login", "rapports", "secret"), ("pasv", True)]
    assert FakeFtp.instances[0].calls[-1] == ("quit",)


@pytest.mark.parametrize("query", ["", "?projects=", "?projects=|%20|"])
def test_no_project_selected_is_refused(client, query):
    response = client.get(f"/reports{query}")

    assert (response.status_code, response.json()) == (400, "No projects selected")


def test_a_malformed_project_number_answers_400(client):
    assert client.get("/reports?projects=../../etc.21.0142").status_code == 400


def test_an_unconfigured_or_unreachable_repository_answers_502(client, monkeypatch):
    monkeypatch.setattr(config, "ftp_host", None)
    assert client.get("/reports?projects=69GT.21.0142").status_code == 502

    def refused(self, host, port):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(config, "ftp_host", "ftp.test")
    monkeypatch.setattr(FakeFtp, "connect", refused)
    response = client.get("/reports?projects=69GT.21.0142")
    assert (response.status_code, response.json()) == (502, {"error": "depot de rapports injoignable"})
