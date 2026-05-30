"""SQLAlchemy engine + session factory, configured from the environment.

Postgres everywhere (matching the other examples). Defaults point at localhost
so the same code runs under docker-compose (DB_HOST=db) and locally.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _database_url() -> str:
    user = os.environ.get("DB_USER", "fastberry")
    password = os.environ.get("DB_PASSWORD", "fastberry")
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", "fastberry")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


engine = create_engine(_database_url(), future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
