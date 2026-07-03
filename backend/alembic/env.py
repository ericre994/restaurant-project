"""Alembic migration environment.

Wired to the app's own models and database URL so migrations never drift from
`app/models.py`:

* target_metadata = app.models.Base.metadata  -> autogenerate diffs against the ORM
* the URL comes from DATABASE_URL (same default as app/db.py), so `alembic
  upgrade head` targets whatever database the app targets — SQLite for dev,
  Postgres when DATABASE_URL points at one.

`render_as_batch=True` makes ALTER operations work on SQLite (it can't ALTER
columns natively; batch mode rebuilds the table), keeping future migrations
runnable on the dev database too.
"""
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make the `app` package importable regardless of the invocation cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Same default as app/db.py — keep them in sync.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
config.set_main_option("sqlalchemy.url", DATABASE_URL)

target_metadata = models.Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
