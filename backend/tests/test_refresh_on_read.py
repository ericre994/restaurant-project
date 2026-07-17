"""Phase 2: refresh-on-read for live (Google) cache rows.

A row past its `expires_at` is refreshed via one lazy Place Details call when its
detail is read; fresh rows, seed rows, and any refresh failure serve straight
from the cache. All offline — the fetch is a plain callable, no key/network.
"""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app import cache, models
from app.db import SessionLocal
from app.providers import google_places


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _fresh_seed(source_id="PID_stale", rating=4.9):
    return {
        "id": source_id, "source": "google_places", "name": "New",
        "categories": ["cafe"], "price_level": 2, "rating": rating,
        "rating_count": 999,
        "location": {"type": "Point", "coordinates": [-75.16, 39.95]},
        "attributes": {"features": {}, "hours": {}}, "address": "1 New St",
        "raw": {"id": source_id},
    }


def _make_google_row(db, *, source_id="PID_stale", rating=4.0, expires_days=-1):
    """Persist a google_places row whose TTL is in the past by default (stale)."""
    row = models.Restaurant(
        source="google_places", source_id=source_id, name="Old",
        location={"type": "Point", "coordinates": [-75.16, 39.95]},
        latitude=39.95, longitude=-75.16, categories=["cafe"], categories_text="cafe",
        price_level=2, rating=rating, rating_count=10,
        attributes={"features": {}, "hours": {}},
        expires_at=models.utcnow() + timedelta(days=expires_days),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --- is_stale ----------------------------------------------------------------

def test_is_stale():
    assert cache.is_stale(models.Restaurant(expires_at=None)) is False  # seed: never expires
    assert cache.is_stale(
        models.Restaurant(expires_at=models.utcnow() - timedelta(hours=1))
    ) is True
    assert cache.is_stale(
        models.Restaurant(expires_at=models.utcnow() + timedelta(hours=1))
    ) is False


# --- refresh_if_stale guards (detached rows — never touch the DB) ------------

def _boom(_pid):
    raise AssertionError("fetch should not be called")


def test_skips_fresh_google_row(db):
    row = models.Restaurant(
        source="google_places", source_id="x",
        expires_at=models.utcnow() + timedelta(days=1), rating=4.0,
    )
    assert cache.refresh_if_stale(db, row, fetch=_boom) is row  # fresh -> no fetch


def test_ignores_non_google_source_even_when_expired(db):
    row = models.Restaurant(
        source="yelp", source_id="y1",
        expires_at=models.utcnow() - timedelta(days=1), rating=4.0,
    )
    assert cache.refresh_if_stale(db, row, fetch=_boom) is row  # seed -> not refreshable


# --- refresh_if_stale live path (persisted google rows) ----------------------

def test_refreshes_stale_row_via_fetch(db):
    row = _make_google_row(db, source_id="PID_stale", rating=4.0)
    called = {}

    def fetch(pid):
        called["pid"] = pid
        return _fresh_seed(source_id="PID_stale", rating=4.9)

    out = cache.refresh_if_stale(db, row, fetch=fetch)
    assert called["pid"] == "PID_stale"        # fetched by place_id
    assert out.rating == 4.9 and out.rating_count == 999  # fields refreshed
    assert not cache.is_stale(out)             # expires_at bumped forward


def test_serves_stale_on_fetch_error(db):
    row = _make_google_row(db, source_id="PID_err", rating=4.0)

    def fetch(pid):
        raise google_places.GooglePlacesError("upstream 500")

    out = cache.refresh_if_stale(db, row, fetch=fetch)
    assert out.rating == 4.0        # unchanged — stale copy served, not a crash
    assert cache.is_stale(out)      # TTL not bumped


def test_refreshed_place_id_is_stored(db):
    row = _make_google_row(db, source_id="OLD_PID")
    out = cache.refresh_if_stale(
        db, row, fetch=lambda pid: _fresh_seed(source_id="NEW_PID")
    )
    assert out.source_id == "NEW_PID"  # keep the permanent key correct


# --- the detail endpoint refreshes on read -----------------------------------

def test_detail_endpoint_refreshes_stale_row(client, db, monkeypatch):
    row = _make_google_row(db, source_id="PID_ep", rating=3.5)
    monkeypatch.setattr(
        google_places, "get_details",
        lambda pid, **k: _fresh_seed(source_id="PID_ep", rating=4.9),
    )
    resp = client.get(f"/restaurants/{row.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["rating"] == 4.9  # served the refreshed value
