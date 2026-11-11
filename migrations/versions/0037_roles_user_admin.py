"""Rôles applicatifs : utilisateur pour tous, admin pour quelques personnes (ADR-0060 du front).

roles reçoit user et admin. Chaque profil existant reçoit le rôle user ; un profil créé ensuite le reçoit
à sa création (core/profile.py). Le rôle admin s'ajoute à user, par la commande
« python -m app.domains.admin.grant_admin <adresse> » ou par l'administration.

Retour arrière : les lignes de user_roles et de roles pour user et admin sont supprimées.
"""

from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("INSERT INTO roles (code, libelle) VALUES ('user', 'Utilisateur'), ('admin', 'Administrateur') ON CONFLICT (code) DO NOTHING")
    op.execute(
        """
        INSERT INTO user_roles (user_id, role_code, granted_at)
        SELECT id, 'user', now() FROM users
        ON CONFLICT (user_id, role_code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM user_roles WHERE role_code IN ('user', 'admin')")
    op.execute("DELETE FROM roles WHERE code IN ('user', 'admin')")
