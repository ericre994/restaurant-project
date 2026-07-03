"""Database engine + session factory.

Defaults to a local SQLite file so the API runs with zero external setup. Point
DATABASE_URL at Postgres (the production target in TDD §5) to switch — the
models are written to map cleanly onto the Postgres schema.
"""
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Anchor the default dev DB to backend/app.db by ABSOLUTE path, not "./app.db".
# A relative path resolves against the process's working directory, so launching
# uvicorn from the repo root (e.g. `--app-dir backend`) would silently create a
# fresh, empty app.db there instead of using the seeded one — the seed appears to
# "vanish". An absolute path makes the dev DB the same file no matter where the
# server is started. Override with DATABASE_URL (e.g. a Postgres DSN) as usual.
_DEFAULT_DB = Path(__file__).resolve().parents[1] / "app.db"   # backend/app.db
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_DEFAULT_DB.as_posix()}")

# check_same_thread is a SQLite-only quirk; harmless to omit on Postgres.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
