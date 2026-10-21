# Profil de l'agent connecté dans la base métier (table users) : créé à sa première requête,
# puis retrouvé par son identifiant Azure (oid). Repris de CurrentProfile du back Symfony.
# Les domaines qui écrivent au nom de l'agent (favoris, enquêtes…) reçoivent ce profil par
# « profile: Profile = Depends(current_profile) ».

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends
from sqlalchemy import text

from app.core.auth import Identity, current_identity
from app.core.errors import Forbidden
from app.database.connection import refonte_row, refonte_transaction


@dataclass(frozen=True)
class Profile:
    id: str
    azure_oid: str
    email: str
    display_name: str | None
    service_id: str | None = None


# Dépendance FastAPI : le profil de l'appelant, créé s'il n'existe pas encore.
def current_profile(identity: Identity = Depends(current_identity)) -> Profile:
    azure_oid = _azure_oid(identity)
    row = refonte_row("SELECT id, azure_oid, email, display_name, service_id FROM users WHERE azure_oid = :oid", oid=azure_oid)
    return _profile(row) if row else provision(identity)


# Crée le profil, ou met à jour son adresse, son nom et sa date de dernière connexion.
# Appelé par PUT /me/sign-in à chaque connexion (et par GET /me).
def provision(identity: Identity) -> Profile:
    azure_oid = _azure_oid(identity)

    with refonte_transaction() as connection:
        # Un profil importé avant la connexion SSO n'a que son adresse : on lui rattache l'oid.
        connection.execute(
            text("UPDATE users SET azure_oid = :oid WHERE email = :email AND azure_oid IS NULL"),
            {"oid": azure_oid, "email": identity.username},
        )
        row = connection.execute(
            text(
                """
                INSERT INTO users (id, azure_oid, email, display_name, created_at, last_login_at)
                VALUES (:id, :oid, :email, :display_name, :at, :at)
                ON CONFLICT (azure_oid) DO UPDATE
                    SET email = EXCLUDED.email,
                        display_name = COALESCE(EXCLUDED.display_name, users.display_name),
                        last_login_at = EXCLUDED.last_login_at
                RETURNING id, azure_oid, email, display_name, service_id
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "oid": azure_oid,
                "email": identity.username,
                "display_name": identity.name,
                "at": datetime.now(UTC),
            },
        ).mappings().one()

    return _profile(dict(row))


# L'oid est la clé du profil : sans oid valide, impossible de savoir à quel profil écrire.
def _azure_oid(identity: Identity) -> str:
    try:
        return str(uuid.UUID(identity.azure_oid or ""))
    except ValueError:
        raise Forbidden("Le jeton ne porte pas d'identifiant Azure (oid).") from None


def _profile(row: dict) -> Profile:
    return Profile(str(row["id"]), str(row["azure_oid"]), row["email"], row["display_name"], row["service_id"])
