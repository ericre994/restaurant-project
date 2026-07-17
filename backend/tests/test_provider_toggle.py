"""Tests for the Stage-1 retrieval provider toggle in recommender.recommend().

RECS_PROVIDER (or the explicit `provider=` arg) selects the retrieval source:
"seed" (the SQL/Yelp path, the dev default) or "google" (the live Text Search
provider). The Google path falls back to the seed path on any GooglePlacesError,
so the user always gets results — proven here with no network and no API key by
monkeypatching the provider's `retrieve`.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models, recommender, schemas, services
from app._proto import proto
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


@pytest.fixture
def user(db):
    return services.get_or_create_user(db, services.DEV_USER_ID)


# --- pure helpers -------------------------------------------------------------

def test_resolve_provider_precedence(monkeypatch):
    monkeypatch.delenv("RECS_PROVIDER", raising=False)
    assert recommender._resolve_provider(None) == "seed"        # default
    assert recommender._resolve_provider("Google") == "google"  # arg wins, lowercased
    monkeypatch.setenv("RECS_PROVIDER", "google")
    assert recommender._resolve_provider(None) == "google"      # env used
    assert recommender._resolve_provider("seed") == "seed"      # arg overrides env


def test_google_query_folds_cuisine():
    c = proto.Constraints(cuisine_keywords=["sushi", "japanese"])
    assert recommender._google_query("dinner tonight", c) == "dinner tonight sushi japanese"
    # already-present keywords aren't duplicated (case-insensitive)
    c2 = proto.Constraints(cuisine_keywords=["Sushi"])
    assert recommender._google_query("great sushi", c2) == "great sushi"
    # empty query with no cuisine still yields something searchable
    assert recommender._google_query("", proto.Constraints()) == "restaurant"


# --- dispatch via recommend() -------------------------------------------------

def test_default_provider_uses_seed(db, user, monkeypatch):
    monkeypatch.delenv("RECS_PROVIDER", raising=False)

    def _boom(*a, **k):  # must never be reached on the seed path
        raise AssertionError("google provider should not be called for seed")

    monkeypatch.setattr(google_places, "retrieve", _boom)
    result = recommender.recommend(db, user, query="tasty")
    assert result.retrieval == "seed"
    assert result.candidate_count == 3  # r1/r2/r3 from conftest


def test_google_provider_is_used_when_selected(db, user, monkeypatch):
    captured = {}
    fake = {
        "id": "g1", "source": "google_places", "name": "G", "categories": [],
        "price_level": 2, "rating": 4.9, "rating_count": 500,
        "location": {"type": "Point", "coordinates": [-75.16, 39.95]},
        "attributes": {"features": {}, "hours": {}}, "address": "x",
    }

    def _fake_retrieve(query, constraints, **kw):
        captured["query"] = query
        return [dict(fake)]

    monkeypatch.setattr(google_places, "retrieve", _fake_retrieve)
    result = recommender.recommend(
        db, user, query="ramen", cuisine=["noodles"], provider="google"
    )
    assert result.retrieval == "google_places"
    assert result.candidate_count == 1
    assert captured["query"] == "ramen noodles"  # cuisine folded into the text query

    # Write-through: the candidate id is rewritten from place_id -> internal UUID,
    # and a persisted row now exists keyed by (source, source_id=place_id).
    (rewritten_id,) = result.by_id
    assert rewritten_id != "g1"
    row = db.execute(
        select(models.Restaurant).where(
            models.Restaurant.source == "google_places",
            models.Restaurant.source_id == "g1",
        )
    ).scalar_one()
    assert row.id == rewritten_id
    assert row.expires_at is not None  # TTL stamped


def test_google_error_falls_back_to_seed(db, user, monkeypatch):
    def _fail(*a, **k):
        raise google_places.GooglePlacesError("GOOGLE_MAPS_API_KEY is not set")

    monkeypatch.setattr(google_places, "retrieve", _fail)
    result = recommender.recommend(db, user, query="tasty", provider="google")
    assert result.retrieval.startswith("seed (google fallback:")
    assert result.candidate_count == 3  # served by the seed path, user still gets results


def test_retrieval_source_is_logged(db, user, monkeypatch):
    def _fail(*a, **k):
        raise google_places.GooglePlacesError("boom")

    monkeypatch.setattr(google_places, "retrieve", _fail)
    result = recommender.recommend(db, user, query="tasty", provider="google")
    req = schemas.RecommendationRequest(query="tasty")
    log = recommender.persist_log(db, user, req, result, latency_ms=1)
    assert log.context["retrieval"] == result.retrieval
    assert log.context["retrieval"].startswith("seed (google fallback:")


# --- the endpoint reads RECS_PROVIDER from the env (it passes no provider arg) --

def test_endpoint_honors_recs_provider_env(monkeypatch):
    """POST /recommendations with RECS_PROVIDER=google routes Stage 1 to Google."""
    fake = {
        "id": "g1", "source": "google_places", "name": "G", "categories": [],
        "price_level": 2, "rating": 4.9, "rating_count": 500,
        "location": {"type": "Point", "coordinates": [-75.16, 39.95]},
        "attributes": {"features": {}, "hours": {}}, "address": "x",
    }
    monkeypatch.setenv("RECS_PROVIDER", "google")
    monkeypatch.setattr(google_places, "retrieve", lambda q, c, **kw: [dict(fake)])

    resp = TestClient(app).post("/recommendations", json={"query": "ramen"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["retrieval"] == "google_places"
    assert body["candidate_count"] == 1
    # id is the internal UUID (write-through), not the raw place_id
    assert body["picks"][0]["restaurant_id"] != "g1"
    assert body["picks"][0]["restaurant"]["id"] == body["picks"][0]["restaurant_id"]
