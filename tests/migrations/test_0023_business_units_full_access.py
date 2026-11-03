from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")


def test_the_former_full_access_agencies_keep_it_and_the_others_do_not(schema_at):
    database = schema_at("0022")
    with database.begin() as connection:
        connection.execute(text("INSERT INTO business_units (code, libelle) VALUES ('DTMG', 'DTMG'), ('69GT', 'Lyon')"))

    command.upgrade(ALEMBIC, "0023")

    with database.connect() as connection:
        assert connection.execute(text("SELECT code, full_access FROM business_units ORDER BY code")).all() == [("69GT", False), ("DTMG", True)]
