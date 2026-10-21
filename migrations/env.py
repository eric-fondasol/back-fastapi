# Point d'entrée d'Alembic : applique les révisions de migrations/versions/ à la base métier.
# Base visée : DB_REFONTE_NAME, ou une autre passée par « alembic -x database=<nom> » (tests).

from alembic import context
from sqlalchemy import create_engine

from app.database.connection import refonte_url

database = context.get_x_argument(as_dictionary=True).get("database")
# Une connexion déjà ouverte peut être fournie par l'appelant (tests) : elle est alors réutilisée.
connection = context.config.attributes.get("connection")


def run(connection) -> None:
    # Pas de modèle SQLAlchemy : les révisions sont écrites à la main, sans autogénération.
    context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)

    with context.begin_transaction():
        context.run_migrations()


if connection is not None:
    run(connection)
else:
    with create_engine(refonte_url(database)).connect() as opened:
        run(opened)
        opened.commit()
