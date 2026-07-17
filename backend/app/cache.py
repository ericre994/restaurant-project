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
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models

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

        db.flush()  # assign row.id for freshly-inserted rows
        out.append({**c, "id": row.id})

    db.commit()
    return out
