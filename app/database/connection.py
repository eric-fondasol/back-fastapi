# Connexions aux bases de données, partagées par tous les domaines :
# - apisolscore (PostgreSQL), lue en lecture seule pour les sites et sondages ;
# - refonte (PostgreSQL), la base métier : affaires, profils, enquêtes, en lecture et écriture ;
# - audit (MySQL), où core/audit.py écrit la table audit_log.

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy import URL, Connection, Row, create_engine, text

from app.core.config import config
from app.core.timing import timed

# Un « engine » gère un pool de connexions : elles restent ouvertes et sont réutilisées d'une
# requête à l'autre, car ouvrir une connexion vers la base distante coûte environ 100 ms.
apisolscore_engine = create_engine(
    # URL.create échappe correctement les caractères spéciaux du mot de passe.
    URL.create(
        "postgresql+psycopg",
        username=config.db_solscore_user,
        password=config.db_solscore_password.get_secret_value(),
        host=config.db_solscore_host,
        port=config.db_solscore_port,
        database=config.db_solscore_name,
    ),
    # Jusqu'à 5 connexions gardées ouvertes, et 10 de plus en pic (fermées ensuite).
    pool_size=5,
    max_overflow=10,
    # Vérifie qu'une connexion est vivante avant de la donner ; une connexion coupée est remplacée.
    pool_pre_ping=True,
    # Renouvelle les connexions de plus de 30 minutes, avant qu'un pare-feu ou le serveur ne les coupe.
    pool_recycle=1800,
)



# URL de la base métier ; « database » permet de viser une autre base du même serveur (tests).
def refonte_url(database: str | None = None) -> URL:
    return URL.create(
        "postgresql+psycopg",
        username=config.db_refonte_user,
        password=config.db_refonte_password.get_secret_value(),
        host=config.db_refonte_host,
        port=config.db_refonte_port,
        database=database or config.db_refonte_name,
    )


refonte_engine = create_engine(refonte_url(), pool_size=5, max_overflow=10, pool_pre_ping=True, pool_recycle=1800)

audit_engine = create_engine(
    URL.create(
        "mysql+pymysql",
        username=config.db_audit_user,
        password=config.db_audit_password.get_secret_value(),
        host=config.db_audit_host,
        port=config.db_audit_port,
        database=config.db_audit_name,
        # utf8mb4 : stocke tous les caractères Unicode (accents, emojis éventuels dans les requêtes).
        query={"charset": "utf8mb4"},
    ),
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,
    pool_recycle=1800,
    # Abandonne au bout de 5 s si la base d'audit ne répond pas, pour ne pas accumuler les attentes.
    connect_args={"connect_timeout": 5},
)


# Exécute une requête et renvoie une seule valeur (première colonne de la première ligne).
def fetch_value(sql: str, **parameters: Any) -> Any:
    # timed("db") : la durée apparaît dans details.timings_ms.db de l'audit.
    with timed("db"), apisolscore_engine.connect() as connection:
        # text() + paramètres :nom : les valeurs sont envoyées séparément du SQL, sans injection possible.
        return connection.execute(text(sql), parameters).scalar()


# Exécute une requête et renvoie les noms des colonnes et toutes les lignes (des tuples, sans conversion).
def fetch_rows(sql: str, **parameters: Any) -> tuple[list[str], Sequence[Row]]:
    with timed("db"), apisolscore_engine.connect() as connection:
        result = connection.execute(text(sql), parameters)
        return list(result.keys()), result.all()


# Ouvre une transaction sur la base métier : validée (commit) à la sortie du bloc, annulée en cas
# d'erreur. Toutes les requêtes du bloc passent par la connexion fournie, pour être atomiques.
@contextmanager
def refonte_transaction() -> Iterator[Connection]:
    with timed("db"), refonte_engine.begin() as connection:
        yield connection


# Lit la base métier et renvoie les lignes sous forme de dictionnaires (colonne → valeur).
def refonte_rows(sql: str, **parameters: Any) -> list[dict[str, Any]]:
    with timed("db"), refonte_engine.connect() as connection:
        return [dict(row) for row in connection.execute(text(sql), parameters).mappings()]


# Lit la base métier et renvoie la première ligne, ou None si aucune ne correspond.
def refonte_row(sql: str, **parameters: Any) -> dict[str, Any] | None:
    rows = refonte_rows(sql, **parameters)
    return rows[0] if rows else None


# Écrit dans la base d'audit. begin() ouvre une transaction validée (commit) à la sortie du bloc,
# ou annulée en cas d'erreur.
def execute_audit(sql: str, **parameters: Any) -> None:
    with audit_engine.begin() as connection:
        connection.execute(text(sql), parameters)
