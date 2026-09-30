from collections.abc import Sequence
from typing import Any

from sqlalchemy import URL, Row, create_engine, text

from app.core.config import config

apisolscore_engine = create_engine(
    URL.create(
        "postgresql+psycopg",
        username=config.db_solscore_user,
        password=config.db_solscore_password.get_secret_value(),
        host=config.db_solscore_host,
        port=config.db_solscore_port,
        database=config.db_solscore_name,
    ),
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=1800,
)


def fetch_value(sql: str, **parameters: Any) -> Any:
    with apisolscore_engine.connect() as connection:
        return connection.execute(text(sql), parameters).scalar()


def fetch_rows(sql: str, **parameters: Any) -> tuple[list[str], Sequence[Row]]:
    with apisolscore_engine.connect() as connection:
        result = connection.execute(text(sql), parameters)
        return list(result.keys()), result.all()
