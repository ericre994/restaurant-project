"""FastAPI app for the list-management capability.

Run:  uvicorn app.main:app --reload   (from the backend/ directory)
Docs: http://127.0.0.1:8000/docs
"""
from fastapi import FastAPI

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
