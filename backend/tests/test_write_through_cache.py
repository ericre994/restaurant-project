"""Phase 1: write-through cache for live (Google) retrieval.

A restaurant retrieved from Google is upserted into `restaurants` so the rest of
the app can reference it: the candidate id is rewritten place_id -> internal
UUID, a row is persisted keyed by (source, source_id), a refresh TTL is stamped,
and the pick is then saveable to a list (the FK resolves). Re-retrieval refreshes
the same row in place rather than duplicating it. All offline — no key/network.
"""
from datetime import timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import cache, models
from app.db import SessionLocal
from app.main import app
from app.providers import google_places


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _cand(place_id, name="G", rating=4.5, count=100):
    return {
        "id": place_id, "source": "google_places", "name": name,
        "categories": ["italian_restaurant"], "price_level": 2,
        "rating": rating, "rating_count": count,
        "location": {"type": "Point", "coordinates": [-75.16, 39.95]},
        "attributes": {"features": {}, "hours": {}}, "address": "1 Test St",
        "raw": {"id": place_id, "x": 1},
    }


# --- cache.upsert_candidates unit tests --------------------------------------

def test_upsert_inserts_new_row_and_rewrites_id(db):
    out = cache.upsert_candidates(db, [_cand("PID_new")], source="google_places")
    assert out[0]["id"] != "PID_new"  # rewritten place_id -> internal UUID
    row = db.execute(
        select(models.Restaurant).where(models.Restaurant.source_id == "PID_new")
    ).scalar_one()
    assert row.id == out[0]["id"]
    assert row.source == "google_places"
    assert row.expires_at is not None          # TTL stamped
    assert (row.latitude, row.longitude) == (39.95, -75.16)  # derived from GeoJSON
    assert row.categories_text == "italian_restaurant"       # derived, lowercased
    assert row.raw == {"id": "PID_new", "x": 1}              # payload retained


def test_upsert_refreshes_existing_row_in_place(db):
    first = cache.upsert_candidates(db, [_cand("PID_dup", rating=4.0)], source="google_places")
    uuid1 = first[0]["id"]

    # Same place_id, changed rating -> same row UUID (so saved lists keep pointing
    # at it), fields refreshed, no duplicate row.
    second = cache.upsert_candidates(db, [_cand("PID_dup", rating=4.9)], source="google_places")
    assert second[0]["id"] == uuid1

    n = db.execute(
        select(func.count()).select_from(models.Restaurant).where(
            models.Restaurant.source_id == "PID_dup"
        )
    ).scalar()
    assert n == 1
    assert db.get(models.Restaurant, uuid1).rating == 4.9


def test_ttl_days_env_override(db, monkeypatch):
    monkeypatch.setenv("RESTAURANT_CACHE_TTL_DAYS", "1")
    before = models.utcnow()
    out = cache.upsert_candidates(db, [_cand("PID_ttl")], source="google_places")
    row = db.get(models.Restaurant, out[0]["id"])
    exp = row.expires_at
    if exp.tzinfo is None:  # SQLite hands datetimes back naive
        exp = exp.replace(tzinfo=timezone.utc)
    assert exp - before < timedelta(days=2)  # ~1 day, not the 7-day default


# --- end-to-end: a Google pick is saveable (the point of write-through) -------

def test_google_pick_is_saveable_to_a_list(monkeypatch):
    monkeypatch.setenv("RECS_PROVIDER", "google")
    monkeypatch.setattr(google_places, "retrieve", lambda q, c, **k: [_cand("PID_save")])
    client = TestClient(app)

    rec = client.post("/recommendations", json={"query": "italian"})
    assert rec.status_code == 200, rec.text
    rid = rec.json()["picks"][0]["restaurant_id"]
    assert rid != "PID_save"  # internal UUID, not the raw place_id

    want = next(l for l in client.get("/lists").json() if l["type"] == "want_to_try")
    added = client.post(f"/lists/{want['id']}/items", json={"restaurant_id": rid})
    # 201 proves the FK resolved -> the Google pick was really persisted.
    assert added.status_code == 201, added.text
