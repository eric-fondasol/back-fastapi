"""Favoris de recherche : n° de devis, coordonnées GPS et parcelles cadastrales (demande du 05/11/2026).

Une table par type, comme les adresses et les affaires (ADR-0023 du front). Chaque favori est désigné par
sa clé naturelle, qui sert de clé primaire avec l'agent : n° de devis (Navision, pas de clé étrangère),
position arrondie au 5e décimal (environ 1 m), référence de la parcelle dans son pays (IDU en France,
n° de lot sans espaces au Québec). Seul ce qu'il faut pour relancer la recherche et l'afficher est
gardé : ni contour de parcelle, ni position de devis, relus à chaque recherche.
"""

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE user_favorite_quotes (
            user_id      uuid                        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            quote_number text                        NOT NULL,
            description  text                        NOT NULL DEFAULT '',
            created_at   timestamp(0) with time zone NOT NULL,
            PRIMARY KEY (user_id, quote_number)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE user_favorite_coordinates (
            user_id    uuid                        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            latitude   numeric(7, 5)               NOT NULL CHECK (latitude BETWEEN -90 AND 90),
            longitude  numeric(8, 5)               NOT NULL CHECK (longitude BETWEEN -180 AND 180),
            created_at timestamp(0) with time zone NOT NULL,
            PRIMARY KEY (user_id, latitude, longitude)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE user_favorite_parcels (
            user_id           uuid                        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            country           text                        NOT NULL CHECK (country IN ('fr', 'ca')),
            reference         text                        NOT NULL,
            municipality_code text,
            municipality_name text,
            section           text,
            number            text                        NOT NULL,
            created_at        timestamp(0) with time zone NOT NULL,
            PRIMARY KEY (user_id, country, reference)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE user_favorite_parcels")
    op.execute("DROP TABLE user_favorite_coordinates")
    op.execute("DROP TABLE user_favorite_quotes")
