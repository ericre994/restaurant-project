"""Write-through cache for externally-sourced restaurants (Google Places).

When Stage-1 retrieval pulls candidates from a *live* provider, they must be
persisted into `restaurants` before the rest of the app can use them: lists,
visits, and notes all FK to `restaurants.id`, so an ephemeral candidate can't be
saved. `upsert_candidates` closes that gap — it insert-or-refreshes each
candidate keyed by `(source, source_id=place_id)`, stamps a refresh TTL
(`expires_at`), and returns the candidates with their `id` **rewritten from the
provider's place_id to our durable internal UUID**, so ranking output and every
downstream save reference the stable id. The hallucination guard still holds:
the ids handed downstream are exactly the ones in the returned candidate set.

TTL note: Google's terms cap caching of non-`place_id` content (~30 days); we
choose a shorter default so ratings/hours stay fresh (see the migration plan's
cache-read strategy). `place_id` itself (in `source_id`) is kept indefinitely.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models

#: Source tag for live Google-sourced rows — the ones that carry a TTL and are
#: eligible for refresh-on-read. Seed rows use other sources and never expire.
GOOGLE_SOURCE = "google_places"

#: Default freshness window for a live-sourced row before its descriptive fields
#: are refreshed. Under Google's ~30-day content-caching ceiling; overridable via
#: RESTAURANT_CACHE_TTL_DAYS.
_DEFAULT_TTL_DAYS = 7


def _ttl() -> timedelta:
    raw = os.getenv("RESTAURANT_CACHE_TTL_DAYS")
    try:
        days = int(raw) if raw else _DEFAULT_TTL_DAYS
    except ValueError:
        days = _DEFAULT_TTL_DAYS
    return timedelta(days=max(days, 0))


def _derive_indexed(candidate: dict) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """Mirror seed.py: pull lat/lon out of the GeoJSON Point and lowercase-join
    categories, so the live path fills the same indexable columns as the seed."""
    coords = (candidate.get("location") or {}).get("coordinates") or [None, None]
    lon, lat = coords[0], coords[1]
    categories = candidate.get("categories") or []
    categories_text = ", ".join(str(c) for c in categories).lower() if categories else None
    return lat, lon, categories_text


def _aware(dt: datetime) -> datetime:
    """SQLite hands datetimes back naive; treat them as UTC for comparison
    (same convention as services._aware)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _apply_candidate(row: "models.Restaurant", c: dict, expires_at: datetime) -> None:
    """Copy a seed-dict candidate's fields onto a Restaurant row and stamp the TTL.
    Shared by the write-through upsert and the refresh-on-read path so both write
    the row identically."""
    lat, lon, categories_text = _derive_indexed(c)
    row.name = c.get("name")
    row.location = c.get("location")
    row.address = c.get("address")
    row.price_level = c.get("price_level")
    row.categories = c.get("categories") or []
    row.attributes = c.get("attributes") or {}
    row.rating = c.get("rating")
    row.rating_count = c.get("rating_count")
    row.latitude = lat
    row.longitude = lon
    row.categories_text = categories_text
    row.raw = c.get("raw")
    row.expires_at = expires_at


def is_stale(row: "models.Restaurant", now: Optional[datetime] = None) -> bool:
    """True when a row's cached fields are past their TTL and should be refreshed.
    A null `expires_at` means never-expire (the static seed) -> never stale."""
    if row.expires_at is None:
        return False
    now = now or models.utcnow()
    return _aware(row.expires_at) <= now


def refresh_if_stale(
    db: Session,
    row: "models.Restaurant",
    *,
    fetch: Callable[[str], Optional[dict]],
    now: Optional[datetime] = None,
) -> "models.Restaurant":
    """Refresh a live-sourced row past its TTL via `fetch(place_id)`; otherwise
    return it untouched.

    `fetch` maps a provider place_id to a fresh seed dict (e.g.
    google_places.get_details). On **any** fetch failure the stale row is served
    unchanged rather than failing the read — a cached-but-stale answer beats a 500
    (same resilience stance as the ranker's fallback). Only rows tagged
    GOOGLE_SOURCE are refreshable; seed rows are returned as-is.
    """
    if row.source != GOOGLE_SOURCE or not is_stale(row, now):
        return row
    try:
        fresh = fetch(row.source_id)
    except Exception:  # network / API / mapping error -> serve the stale copy
        return row
    if fresh is None:  # place gone or unusable payload -> keep what we have
        return row
    # Google may hand back a refreshed place_id; keep source_id correct (it is our
    # permanent key). The internal UUID / row identity never changes.
    new_id = fresh.get("id")
    if new_id and new_id != row.source_id:
        row.source_id = new_id
    _apply_candidate(row, fresh, (now or models.utcnow()) + _ttl())
    db.commit()
    db.refresh(row)
    return row


def upsert_candidates(
    db: Session,
    candidates: List[dict],
    *,
    source: str,
    now: Optional[datetime] = None,
) -> List[dict]:
    """Insert-or-refresh `candidates` into `restaurants`, returning them with `id`
    rewritten to the internal UUID.

    `source_id` is the candidate's incoming `id` (the provider place_id). Existing
    rows are refreshed in place (same UUID, so saved lists/visits/notes keep
    pointing at them); new rows get a fresh UUID. Every touched row's
    `expires_at` is bumped to now + TTL.
    """
    now = now or models.utcnow()
    expires_at = now + _ttl()
    out: List[dict] = []
    for c in candidates:
        place_id = c["id"]
        row = db.execute(
            select(models.Restaurant).where(
                models.Restaurant.source == source,
                models.Restaurant.source_id == place_id,
            )
        ).scalar_one_or_none()
        if row is None:
            row = models.Restaurant(source=source, source_id=place_id)
            db.add(row)

        _apply_candidate(row, c, expires_at)
        db.flush()  # assign row.id for freshly-inserted rows
        out.append({**c, "id": row.id})

    db.commit()
    return out
