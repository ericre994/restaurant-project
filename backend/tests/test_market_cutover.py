"""Phase 4: market cutover — the live (Google) market defaults to an NYC search
center when a request supplies no location, while the seed path stays unfiltered.

Tests capture the `near` handed to the provider by monkeypatching
google_places.retrieve; all offline, no key/network.
"""
import pytest

from app import recommender, services
from app.db import SessionLocal
from app.providers import google_places


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def user(db):
    return services.get_or_create_user(db, services.DEV_USER_ID)


@pytest.fixture
def capture_near(monkeypatch):
    """Monkeypatch the provider to record the constraints.near it receives."""
    box = {}
    monkeypatch.setattr(
        google_places, "retrieve", lambda q, c, **k: (box.update(near=c.near) or [])
    )
    return box


def test_google_no_location_defaults_to_nyc_center(db, user, capture_near, monkeypatch):
    monkeypatch.delenv("RECS_DEFAULT_CENTER", raising=False)
    recommender.recommend(db, user, query="dinner", provider="google")
    assert capture_near["near"] == recommender._NYC_CENTER


def test_default_center_env_override(db, user, capture_near, monkeypatch):
    monkeypatch.setenv("RECS_DEFAULT_CENTER", "40.0,-74.0")
    recommender.recommend(db, user, query="dinner", provider="google")
    assert capture_near["near"] == (40.0, -74.0)


def test_malformed_default_center_falls_back_to_nyc(db, user, capture_near, monkeypatch):
    monkeypatch.setenv("RECS_DEFAULT_CENTER", "not-coords")
    recommender.recommend(db, user, query="dinner", provider="google")
    assert capture_near["near"] == recommender._NYC_CENTER


def test_explicit_location_overrides_default(db, user, capture_near):
    recommender.recommend(db, user, query="dinner", lat=41.0, lng=-73.0, provider="google")
    assert capture_near["near"] == (41.0, -73.0)


def test_seed_mode_applies_no_default_center(db, user, monkeypatch):
    # Seed path: no location -> near stays None -> no geo filter -> the full seed.
    monkeypatch.delenv("RECS_PROVIDER", raising=False)
    result = recommender.recommend(db, user, query="dinner")
    assert result.retrieval == "seed"
    assert result.candidate_count == 3  # r1/r2/r3, unfiltered
