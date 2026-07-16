"""Backend application package.

Loads ``backend/.env`` into the process environment on first import, so local
secrets (``GOOGLE_MAPS_API_KEY``, ``ANTHROPIC_API_KEY``, an optional
``DATABASE_URL``, ...) are available to every submodule. Importing any ``app.*``
module runs this package first, which matters because ``app.db`` reads
``DATABASE_URL`` at import time — the .env must be loaded before then.

Two deliberate choices:

* **Absolute path to backend/.env**, not CWD-relative — same reasoning as the
  absolute dev-DB path in ``app/db.py``: the server may be launched from any
  directory (repo root, ``backend/``, ...), and a relative ``.env`` lookup would
  silently find nothing.
* **``override=False``** (the ``load_dotenv`` default): a real environment
  variable already set in the shell (``$env:FOO`` / ``export FOO``) or by the
  test harness (``tests/conftest.py`` sets ``DATABASE_URL`` before import) wins
  over the file. The file only fills in vars that are otherwise unset.

If ``python-dotenv`` isn't installed yet, this is a no-op and the app still runs
reading real environment variables — so the dependency is a convenience, not a
hard requirement.
"""
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    pass
else:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
