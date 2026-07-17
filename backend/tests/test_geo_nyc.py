"""Phase 3: NYC location resolution — curated neighborhood table + the layered
_resolve_location (explicit lat/lng -> DB index -> NYC table -> Geocoding API).

conftest seeds Philadelphia rows, so the DB index still resolves Philly names
(regression), while NYC-only names resolve via the curated table and arbitrary
text falls through to a (mocked) Geocoding call.
"""
import pytest

from app import geo_nyc, recommender
from app.db import SessionLocal
from app.providers import google_geocoding


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


# --- curated NYC table -------------------------------------------------------

def test_nyc_index_resolves_exact_and_fuzzy():
    assert geo_nyc.INDEX.resolve("williamsburg") == geo_nyc.NYC_NEIGHBORHOODS["williamsburg"]
    assert geo_nyc.INDEX.resolve("willamsburg") == geo_nyc.NYC_NEIGHBORHOODS["williamsburg"]  # typo
    assert geo_nyc.INDEX.resolve("astoria") == geo_nyc.NYC_NEIGHBORHOODS["astoria"]
    assert geo_nyc.INDEX.resolve("zzz-not-a-place") is None


# --- layered _resolve_location ----------------------------------------------

def test_explicit_latlng_wins(db):
    assert recommender._resolve_location(db, "williamsburg", 40.5, -73.5) == (40.5, -73.5)


def test_philly_seed_name_still_resolves_locally(db):
    # Regression: chinatown -> Philadelphia via the DB index (ZIP 19107 present),
    # NOT the NYC curated entry — the DB index is tried first.
    lat, lon = recommender._resolve_location(db, "chinatown", None, None)
    assert 39.0 < lat < 40.5 and lon < -74.5  # Philly (~-75.15), not NYC (~-73.99)


def test_nyc_neighborhood_resolves_via_curated_table(db):
    # williamsburg isn't in the Philly seed -> falls through to the NYC table.
    assert recommender._resolve_location(db, "williamsburg", None, None) == (
        geo_nyc.NYC_NEIGHBORHOODS["williamsburg"]
    )


def test_geocoding_fallback_for_arbitrary_text(db, monkeypatch):
    monkeypatch.setattr(google_geocoding, "geocode", lambda text, **k: (40.0, -74.0))
    assert recommender._resolve_location(db, "1600 Nowhere Blvd", None, None) == (40.0, -74.0)


def test_unknown_location_raises_with_guidance(db, monkeypatch):
    monkeypatch.setattr(google_geocoding, "geocode", lambda text, **k: None)
    with pytest.raises(ValueError, match="unknown location"):
        recommender._resolve_location(db, "qzzx-nowhere", None, None)
