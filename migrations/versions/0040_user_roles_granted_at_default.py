"""user_roles.granted_at prend now() par défaut (12/11/2026) : user_roles devient une table administrable par l'éditeur
générique de l'administration, qui remplace l'écran « Utilisateurs ». Sans valeur par défaut, l'administrateur
devrait saisir la date à la main pour donner un rôle.

Retour arrière : la valeur par défaut est retirée.
"""

from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_roles ALTER COLUMN granted_at SET DEFAULT now()")


def downgrade() -> None:
    op.execute("ALTER TABLE user_roles ALTER COLUMN granted_at DROP DEFAULT")
