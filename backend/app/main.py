"""FastAPI app for the list-management capability.

Run:  uvicorn app.main:app --reload   (from the backend/ directory)
Docs: http://127.0.0.1:8000/docs
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import models
from .db import engine
from .routers import lists, me, recommendations, restaurants, visits

# Dev convenience: create tables on startup. For Postgres, generate Alembic
# migrations from these models instead (see backend/README.md).
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Restaurant App — Lists API", version="0.1.0")
app.include_router(me.router)
app.include_router(lists.router)
app.include_router(visits.router)
app.include_router(restaurants.router)
app.include_router(recommendations.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


# Dev test harness: a single-page vanilla-JS UI for exercising list interactions,
# served same-origin at /app (so it needs no CORS). html=True serves index.html
# at the mount root. Kept last so it doesn't shadow the API routes above.
_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/app", StaticFiles(directory=str(_STATIC_DIR), html=True), name="app")
