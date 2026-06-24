"""Database engine + session factory.

Defaults to a local SQLite file so the API runs with zero external setup. Point
DATABASE_URL at Postgres (the production target in TDD §5) to switch — the
models are written to map cleanly onto the Postgres schema.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

# check_same_thread is a SQLite-only quirk; harmless to omit on Postgres.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
