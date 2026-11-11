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


# Le métier de l'agent vient de sa business unit (31GT → GT) ; vide hors agence ou code inconnu.
# Ses rôles applicatifs (user, admin) viennent de user_roles (migration 0037, ADR-0060 du front).
PROFILE_SELECT = """
    SELECT users.id, users.azure_oid, users.email, users.display_name, users.department,
           users.business_unit_code, business_units.business_line,
           ARRAY(SELECT role_code FROM user_roles WHERE user_roles.user_id = users.id ORDER BY role_code) AS roles
    FROM users LEFT JOIN business_units ON business_units.code = users.business_unit_code
"""

USER_ROLE = "user"
ADMIN_ROLE = "admin"


@dataclass(frozen=True)
class Profile:
    id: str
    azure_oid: str
    email: str
    display_name: str | None
    department: str | None = None
    business_unit_code: str | None = None
    business_line: str | None = None
    roles: tuple[str, ...] = ()

    @property
    def is_admin(self) -> bool:
        return ADMIN_ROLE in self.roles


# Dépendance FastAPI : le profil de l'appelant, créé s'il n'existe pas encore.
def current_profile(identity: Identity = Depends(current_identity)) -> Profile:
    azure_oid = _azure_oid(identity)
    row = refonte_row(f"{PROFILE_SELECT} WHERE users.azure_oid = :oid", oid=azure_oid)
    return _profile(row) if row else provision(identity)


# Dépendance FastAPI des routes /admin/… : 403 si l'appelant n'a pas le rôle admin.
def admin_profile(profile: Profile = Depends(current_profile)) -> Profile:
    if not profile.is_admin:
        raise Forbidden("Réservé aux administrateurs.")
    return profile


# Crée le profil, ou met à jour son adresse, son nom et sa date de dernière connexion.
# Un profil créé reçoit le rôle user ; un profil existant garde ses rôles (un accès retiré ne revient pas).
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
                RETURNING id, (xmax = 0) AS created
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
        if row["created"]:
            connection.execute(
                text("INSERT INTO user_roles (user_id, role_code, granted_at) VALUES (:id, :role, now()) ON CONFLICT DO NOTHING"),
                {"id": row["id"], "role": USER_ROLE},
            )
        profile = connection.execute(text(f"{PROFILE_SELECT} WHERE users.id = :id"), {"id": row["id"]}).mappings().one()

    return _profile(dict(profile))


# L'oid est la clé du profil : sans oid valide, impossible de savoir à quel profil écrire.
def _azure_oid(identity: Identity) -> str:
    try:
        return str(uuid.UUID(identity.azure_oid or ""))
    except ValueError:
        raise Forbidden("Le jeton ne porte pas d'identifiant Azure (oid).") from None


def _profile(row: dict) -> Profile:
    return Profile(
        str(row["id"]),
        str(row["azure_oid"]),
        row["email"],
        row["display_name"],
        row["department"],
        row["business_unit_code"],
        row["business_line"],
        tuple(row.get("roles") or ()),
    )
