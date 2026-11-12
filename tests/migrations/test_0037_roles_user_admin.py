from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")


def rows(database, query):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def test_existing_users_get_the_user_role_and_the_two_roles_exist(schema_at):
    database = schema_at("0036")
    with database.begin() as connection:
        connection.execute(text("INSERT INTO users (id, email, created_at) VALUES ('00000000-0000-0000-0000-000000000001', 'a@fondasol.fr', now())"))

    command.upgrade(ALEMBIC, "0037")

    assert rows(database, "SELECT code, libelle FROM roles ORDER BY code") == [("admin", "Administrateur"), ("user", "Utilisateur")]
    assert rows(database, "SELECT user_id::text, role_code FROM user_roles") == [("00000000-0000-0000-0000-000000000001", "user")]


def test_downgrade_removes_the_roles_and_their_grants(schema_at):
    database = schema_at("0037")
    with database.begin() as connection:
        connection.execute(text("INSERT INTO users (id, email, created_at) VALUES ('00000000-0000-0000-0000-000000000001', 'a@fondasol.fr', now())"))
        connection.execute(text("INSERT INTO user_roles VALUES ('00000000-0000-0000-0000-000000000001', 'admin', now())"))

    command.downgrade(ALEMBIC, "0036")

    assert rows(database, "SELECT * FROM roles") == []
    assert rows(database, "SELECT * FROM user_roles") == []
