import uuid

import pytest
from sqlalchemy import text

from app.core.auth import Identity
from app.core.errors import Forbidden
from app.core.profile import current_profile, provision

OID = "6F9619FF-8B86-D011-B42D-00C04FC964FF"


def stored_users(engine):
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text("SELECT * FROM users ORDER BY email")).mappings()]


def test_the_first_request_creates_the_profile_from_the_token(refonte_database):
    profile = current_profile(Identity("jean.dupont@fondasol.fr", OID, "Jean Dupont"))

    assert profile.azure_oid == OID.lower()
    assert (profile.email, profile.display_name) == ("jean.dupont@fondasol.fr", "Jean Dupont")
    assert [user["id"] for user in stored_users(refonte_database)] == [uuid.UUID(profile.id)]


def test_the_next_requests_find_the_same_profile_without_touching_it(refonte_database):
    created = current_profile(Identity("jean.dupont@fondasol.fr", OID, "Jean Dupont"))
    login = stored_users(refonte_database)[0]["last_login_at"]

    found = current_profile(Identity("jean.dupont@fondasol.fr", OID.lower(), None))

    assert found == created
    assert stored_users(refonte_database)[0]["last_login_at"] == login


def test_signing_in_again_updates_the_address_and_keeps_a_known_name(refonte_database):
    created = provision(Identity("jean.dupont@fondasol.fr", OID, "Jean Dupont"))

    signed_in = provision(Identity("j.dupont@fondasol.fr", OID, None))

    assert signed_in.id == created.id
    assert (signed_in.email, signed_in.display_name) == ("j.dupont@fondasol.fr", "Jean Dupont")
    assert len(stored_users(refonte_database)) == 1


def test_a_profile_imported_before_sso_gets_its_azure_identifier(refonte_database):
    imported = uuid.uuid4()
    with refonte_database.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id, email, created_at) VALUES (:id, 'jean.dupont@fondasol.fr', now())"),
            {"id": imported},
        )

    profile = provision(Identity("jean.dupont@fondasol.fr", OID, "Jean Dupont"))

    assert profile.id == str(imported)
    assert stored_users(refonte_database)[0]["azure_oid"] == uuid.UUID(OID)


@pytest.mark.parametrize("azure_oid", [None, "", "not-an-oid"])
def test_a_token_without_azure_identifier_is_forbidden(refonte_database, azure_oid):
    with pytest.raises(Forbidden):
        current_profile(Identity("jean.dupont@fondasol.fr", azure_oid, "Jean Dupont"))

    assert stored_users(refonte_database) == []
