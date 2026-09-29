import os

import redis
from sqlalchemy import URL, create_engine

base = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)

base_apisolscore = create_engine(
    URL.create(
        "postgresql+psycopg",
        username=os.getenv("DB_SOLSCORE_USER"),
        password=os.getenv("DB_SOLSCORE_PASSWORD"),
        host=os.getenv("DB_SOLSCORE_HOST"),
        port=int(os.getenv("DB_SOLSCORE_PORT", "5432")),
        database=os.getenv("DB_SOLSCORE_NAME"),
    ),
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=1800,
)

cache = redis.Redis.from_url(os.environ["REDIS_URL"])
