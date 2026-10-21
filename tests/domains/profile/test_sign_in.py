import pytest
from sqlalchemy import text

from tests.domains.profile.test_routes import OTHER, call, client  # noqa: F401


def test_records_the_azure_department_raw_and_replaces_it_at_the_next_sign_in(client, refonte_database):
    assert call(client, "PUT", "/me/sign-in", {"department": " 44EN "}).status_code == 204
    assert call(client, "GET", "/me").json()["serviceId"] == "44EN"

    call(client, "PUT", "/me/sign-in", {"department": "GFDT"})
    assert call(client, "GET", "/me").json()["serviceId"] == "GFDT"


def test_an_empty_or_missing_department_in_azure_clears_the_recorded_one(client, refonte_database):
    call(client, "PUT", "/me/sign-in", {"department": "44EN"})

    call(client, "PUT", "/me/sign-in", {"department": "  "})
    assert call(client, "GET", "/me").json()["serviceId"] is None

    call(client, "PUT", "/me/sign-in", {"department": "95GT"})
    call(client, "PUT", "/me/sign-in", {"department": None})
    assert call(client, "GET", "/me").json()["serviceId"] is None


def test_each_agent_records_their_own_department(client, refonte_database):
    call(client, "PUT", "/me/sign-in", {"department": "44EN"})
    call(client, "PUT", "/me/sign-in", {"department": "GFCO"}, identity=OTHER)

    assert call(client, "GET", "/me").json()["serviceId"] == "44EN"
    assert call(client, "GET", "/me", identity=OTHER).json()["serviceId"] == "GFCO"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"department": 44}, "department doit etre un texte de 100 caracteres au plus, ou null."),
        ({"department": "x" * 101}, "department doit etre un texte de 100 caracteres au plus, ou null."),
    ],
)
def test_refuses_an_invalid_department(client, refonte_database, body, message):
    response = call(client, "PUT", "/me/sign-in", body)

    assert (response.status_code, response.json()) == (400, {"errors": message})


def test_each_sign_in_updates_the_last_login_date(client, refonte_database):
    call(client, "PUT", "/me/sign-in", {"department": "GFIT"})
    with refonte_database.begin() as connection:
        connection.execute(text("UPDATE users SET last_login_at = '2026-10-09 09:43:16+00'"))

    assert call(client, "PUT", "/me/sign-in", {"department": "GFIT"}).status_code == 204

    with refonte_database.connect() as connection:
        last_login = connection.execute(text("SELECT last_login_at FROM users")).scalar_one()
    assert last_login.isoformat() > "2026-10-10"


def test_the_first_sign_in_creates_the_profile_with_its_department(client, refonte_database):
    call(client, "PUT", "/me/sign-in", {"department": "44EN"})

    with refonte_database.connect() as connection:
        assert connection.execute(text("SELECT email, service_id FROM users")).one() == ("spike@fondasol.fr", "44EN")


def test_a_sign_in_without_department_keeps_the_known_one(client, refonte_database):
    call(client, "PUT", "/me/sign-in", {"department": "GFIT"})

    assert call(client, "PUT", "/me/sign-in", {}).status_code == 204
    assert call(client, "GET", "/me").json()["serviceId"] == "GFIT"
