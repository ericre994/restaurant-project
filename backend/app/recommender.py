"""Adapter that runs the prototype's retrieve -> rank -> render pipeline against
the DB instead of the seed JSON.

The pipeline logic itself is NOT reimplemented here — we import the prototype
module (`prototype/recommend.py`) so it stays the single source of truth. This
adapter only: (a) turns DB Restaurant rows into the dict shape the prototype
expects, (b) builds Constraints from the request, and (c) derives a TasteProfile
from the user's visit history.

Stage 1 retrieval (`_sql_retrieve`) runs in SQL: price, a geo bounding box on
indexed latitude/longitude, and cuisine on categories_text, ordered by rating as
the pre-rank — so we never scan every row. Only the two filters SQL can't express
portably stay in Python: the exact circular radius (the bbox is a coarse square)
and open-hours (day-of-week + past-midnight logic over a JSON blob). On Postgres
these become a geography/GIST radius query and a pgvector pre-rank (TDD §4.1).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import cos, radians
from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import models, schemas, taste
from ._proto import proto

LANDMARKS = proto.LANDMARKS


@dataclass
class RecommendationResult:
    picks: list
    mode: str
    by_id: dict
    candidate_count: int
    profile: "proto.TasteProfile"


def _to_seed_dict(r: models.Restaurant) -> dict:
    """Restaurant row -> the dict shape the prototype's pipeline consumes."""
    return {
        "id": r.id,
        "source": r.source,
        "name": r.name,
        "categories": r.categories or [],
        "price_level": r.price_level,
        "rating": r.rating,
        "rating_count": r.rating_count,
        "location": r.location,          # GeoJSON {"type","coordinates":[lon,lat]}
        "attributes": r.attributes or {},  # {"features": {...}, "hours": {...}}
        "address": r.address,
    }


def load_taste_profile(db: Session, user: models.User) -> "proto.TasteProfile":
    """Read the persisted taste_profiles row (app.taste) into the prototype's
    TasteProfile shape. The row is kept fresh by taste.refresh() on visit/feedback;
    an empty profile (cold start) is fine — recommendations are just less personal.
    """
    row = taste.get_or_create(db, user)
    return proto.TasteProfile(
        cuisines_preferred=row.cuisines_preferred or {},
        price_pref=row.price_pref or [1, 2, 3],
        dietary_restrictions=row.dietary_restrictions or [],
        ambiance_prefs=row.ambiance_prefs or [],
        summary=row.derived_summary or "",
    )


def _resolve_location(
    near: Optional[str], lat: Optional[float], lng: Optional[float]
) -> Optional[Tuple[float, float]]:
    if lat is not None and lng is not None:
        return (lat, lng)
    if near:
        coords = proto.LANDMARKS.get(near.lower())
        if coords is None:
            raise ValueError(
                f"unknown landmark '{near}'; known: {', '.join(proto.LANDMARKS)}"
            )
        return coords
    return None


def _sql_retrieve(db: Session, c: "proto.Constraints") -> list:
    """Stage 1, in SQL: hard-filter + rating pre-rank, return capped seed dicts.

    Pushes price, a geo bounding box (indexed lat/lng), and cuisine into the
    query; refines the coarse bbox to an exact radius and applies open-hours in
    Python (both hard to express portably in SQL). Result order matches the
    prototype's `retrieve`: best-rated first, capped at CANDIDATE_CAP.
    """
    cap = proto.CANDIDATE_CAP
    coords = c.near

    stmt = select(models.Restaurant)
    if c.price_max is not None:
        stmt = stmt.where(models.Restaurant.price_level <= c.price_max)
    if c.cuisine_keywords:
        stmt = stmt.where(
            or_(
                *[
                    models.Restaurant.categories_text.like(f"%{k.lower()}%")
                    for k in c.cuisine_keywords
                ]
            )
        )
    if coords is not None:
        lat0, lon0 = coords
        dlat = c.radius_km / 111.0  # ~111 km per degree of latitude
        coslat = cos(radians(lat0))
        dlon = c.radius_km / (111.0 * coslat) if abs(coslat) > 1e-6 else 180.0
        stmt = stmt.where(
            models.Restaurant.latitude.is_not(None),
            models.Restaurant.latitude.between(lat0 - dlat, lat0 + dlat),
            models.Restaurant.longitude.between(lon0 - dlon, lon0 + dlon),
        )

    # Pre-rank by rating quality (stand-in for the pgvector step).
    stmt = stmt.order_by(
        models.Restaurant.rating.desc(),
        models.Restaurant.rating_count.desc(),
    )
    # The geo bbox already bounds the row count; otherwise cap in SQL (over-fetch
    # when we still need a Python open-hours pass that may drop some rows).
    if coords is None:
        over_fetch = cap * 10 if (c.open_now and c.when is not None) else cap
        stmt = stmt.limit(over_fetch)

    seed = [_to_seed_dict(r) for r in db.scalars(stmt)]

    if coords is not None:  # exact circular radius (the bbox was a square)
        seed = [
            s
            for s in seed
            if proto.haversine_km(coords, proto.latlon(s)) <= c.radius_km
        ]
    if c.open_now and c.when is not None:
        seed = [s for s in seed if proto.is_open_at(s, c.when)]

    return seed[:cap]


def recommend(
    db: Session,
    user: models.User,
    *,
    query: str,
    near: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    radius_km: float = 4.0,
    price_max: Optional[int] = None,
    cuisine: Optional[List[str]] = None,
    open_now: bool = False,
    party_size: int = 2,
) -> RecommendationResult:
    """Run the pipeline and return the picks plus everything the log needs.

    `mode` is 'llm', 'llm-repair', or a 'fallback (...)' string — fallback when
    no ANTHROPIC_API_KEY is set or the LLM call/parse fails (PRD reliability req).
    """
    coords = _resolve_location(near, lat, lng)
    constraints = proto.Constraints(
        party_size=party_size,
        near=coords,
        radius_km=radius_km,
        price_max=price_max,
        cuisine_keywords=cuisine or [],
        open_now=open_now,
        when=datetime.now() if open_now else None,
    )
    profile = load_taste_profile(db, user)

    # Stage 1 retrieval runs in SQL (see _sql_retrieve); stages 2-3 reuse the
    # prototype unchanged.
    candidates = _sql_retrieve(db, constraints)
    compact = [proto.compact_candidate(r, constraints) for r in candidates]
    picks, mode = proto.rank(query, profile, compact, constraints)
    by_id = {r["id"]: r for r in candidates}
    return RecommendationResult(
        picks=picks,
        mode=mode,
        by_id=by_id,
        candidate_count=len(candidates),
        profile=profile,
    )


def persist_log(
    db: Session,
    user: models.User,
    request: "schemas.RecommendationRequest",
    result: RecommendationResult,
    latency_ms: int,
) -> models.RecommendationLog:
    """Write the recommendation_logs row (TDD §4.5). Returns the saved log.

    token_usage / cost_estimate stay null: the prototype's call_llm discards the
    LLM usage object, so wiring those would mean surfacing usage from the
    prototype. Left as a follow-up rather than guessed.
    """
    used_llm = result.mode.startswith("llm")
    context = {
        "filters": {
            "near": request.near,
            "lat": request.lat,
            "lng": request.lng,
            "radius_km": request.radius_km,
            "price_max": request.price_max,
            "cuisine": request.cuisine,
            "open_now": request.open_now,
            "party_size": request.party_size,
        },
        "taste_snapshot": result.profile.compact(),
        "ranking_mode": result.mode,
    }
    log = models.RecommendationLog(
        user_id=user.id,
        query_text=request.query,
        context=context,
        candidate_set=[
            {"id": c["id"], "source": c.get("source")} for c in result.by_id.values()
        ],
        llm_model=proto.MODEL if used_llm else None,
        prompt_version=proto.PROMPT_VERSION,
        llm_response=result.picks,
        shown_restaurant_ids=[p["restaurant_id"] for p in result.picks],
        latency_ms=latency_ms,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
