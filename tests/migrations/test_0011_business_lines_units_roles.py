import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")


@pytest.fixture
def before_0011(schema_at):
    return schema_at("0010")


def rows(database, query):
    with database.connect() as connection:
        return connection.execute(text(query)).all()


def test_business_units_come_from_the_former_services_with_the_business_line_of_agencies_only(before_0011):
    with before_0011.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO services (id, libelle, full_access, tab) VALUES
                    ('31GT', 'Toulouse', false, 1), ('44EN', '', false, 2), ('LUGT', 'Luxembourg', false, 1),
                    ('DTMG', NULL, true, 2), ('MSGT', '', false, 2)
                """
            )
        )
        connection.execute(text("INSERT INTO email_services (id, service_code) VALUES ('a@fondasol.fr', 'GFIT'), ('b@fondasol.fr', '31GT')"))

    command.upgrade(ALEMBIC, "0011")

    assert rows(before_0011, "SELECT code, libelle, business_line FROM business_units ORDER BY code") == [
        ("31GT", "Toulouse", "GT"),
        ("44EN", "44EN", "EN"),
        ("DTMG", "DTMG", None),
        ("GFIT", "GFIT", None),
        ("LUGT", "Luxembourg", "GT"),
        ("MSGT", "MSGT", None),
    ]
    assert [code for (code,) in rows(before_0011, "SELECT code FROM business_lines ORDER BY position")] == ["GT", "MG", "CO", "EN", "HY", "PS", "LB", "RD"]


def test_the_azure_department_moves_to_department_and_only_a_known_code_becomes_the_business_unit(before_0011):
    with before_0011.begin() as connection:
        connection.execute(text("INSERT INTO services (id, libelle, full_access, tab) VALUES ('31GT', 'Toulouse', false, 1)"))
        connection.execute(
            text(
                """
                INSERT INTO users (id, email, service_id, created_at) VALUES
                    ('00000000-0000-0000-0000-000000000001', 'a@fondasol.fr', '31GT', now()),
                    ('00000000-0000-0000-0000-000000000002', 'b@fondasol.fr', 'ZZ99', now()),
                    ('00000000-0000-0000-0000-000000000003', 'c@fondasol.fr', NULL, now())
                """
            )
        )

    command.upgrade(ALEMBIC, "0011")

    assert rows(before_0011, "SELECT email, department, business_unit_code FROM users ORDER BY email") == [
        ("a@fondasol.fr", "31GT", "31GT"),
        ("b@fondasol.fr", "ZZ99", None),
        ("c@fondasol.fr", None, None),
    ]


def test_a_role_is_granted_once_per_user_and_goes_with_the_user(refonte_database):
    with refonte_database.begin() as connection:
        connection.execute(text("INSERT INTO roles (code, libelle) VALUES ('admin', 'Administrateur')"))
        connection.execute(text("INSERT INTO users (id, email, created_at) VALUES ('00000000-0000-0000-0000-000000000001', 'a@fondasol.fr', now())"))
        connection.execute(text("INSERT INTO user_roles (user_id, role_code, granted_at) VALUES ('00000000-0000-0000-0000-000000000001', 'admin', now())"))

    with pytest.raises(Exception, match="duplicate key"), refonte_database.begin() as connection:
        connection.execute(text("INSERT INTO user_roles (user_id, role_code, granted_at) VALUES ('00000000-0000-0000-0000-000000000001', 'admin', now())"))

    with refonte_database.begin() as connection:
        connection.execute(text("DELETE FROM users"))
    assert rows(refonte_database, "SELECT * FROM user_roles") == []
