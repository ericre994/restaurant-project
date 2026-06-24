"""Taste-profile persistence + aggregation (TDD §4.5).

`refresh()` recomputes a user's behaviorally-derived preferences (cuisine weights,
price band, NL summary) from their visits and recommendation feedback. Explicit
onboarding prefs (dietary_restrictions, ambiance_prefs) are set via PUT
/me/taste-profile and are always preserved here.

Two design rules worth knowing:
  - Derived fields are recomputed from scratch each run (not added to the stored
    values), so repeated refreshes don't double-count the same visit/feedback.
  - With zero behavioral signal, the derived cuisine/price fields are left as-is,
    so cold-start onboarding seeds set via PUT survive until real behavior exists.

The summary is templated, not LLM-generated (TDD §5.1 envisions an LLM summary);
generating it with the model is a follow-up that needs an API key.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from ._proto import proto

# Visit sentiment -> cuisine weight.
_SENTIMENT_WEIGHT = {"loved": 1.0, "liked": 0.6, "wouldnt_return": -0.8}
_DEFAULT_VISIT_WEIGHT = 0.4

# Recommendation feedback action -> cuisine weight.
_ACTION_WEIGHT = {
    "saved": 0.7,
    "visited": 0.8,
    "thumbs_up": 0.6,
    "dismissed": -0.5,
    "thumbs_down": -0.7,
}

# Generic Yelp umbrella categories that sit on nearly every restaurant and carry
# no taste signal — dropped before weighting so real cuisines surface (the
# category-level equivalent of search stopwords). Compared lowercased.
_CATEGORY_STOPWORDS = {
    "food",
    "restaurants",
    "nightlife",
    "bars",
    "event planning & services",
    "caterers",
    "food trucks",
    "food stands",
    "food court",
    "specialty food",
    "shopping",
    "arts & entertainment",
}


def _cuisines(restaurant: models.Restaurant) -> list:
    """A restaurant's categories with umbrella/stopword tags removed."""
    return [
        c for c in (restaurant.categories or []) if c.lower() not in _CATEGORY_STOPWORDS
    ]


def get_or_create(db: Session, user: models.User) -> models.TasteProfile:
    profile = db.scalar(
        select(models.TasteProfile).where(models.TasteProfile.user_id == user.id)
    )
    if profile is None:
        profile = models.TasteProfile(
            user_id=user.id,
            cuisines_preferred={},
            price_pref=[1, 2, 3],
            dietary_restrictions=[],
            ambiance_prefs=[],
        )
        # Seed a deterministic template summary (no LLM call for an empty profile).
        profile.derived_summary = _template_summary(profile)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def refresh(db: Session, user: models.User) -> models.TasteProfile:
    """Recompute derived prefs from visits + recommendation feedback."""
    profile = get_or_create(db, user)

    weights: dict[str, float] = {}
    prices: list[int] = []
    had_signal = False

    # Signal 1: visit history (sentiment-weighted).
    visits = db.scalars(
        select(models.Visit).where(models.Visit.user_id == user.id)
    ).all()
    for v in visits:
        had_signal = True
        r = v.restaurant
        if r is None:
            continue
        w = _SENTIMENT_WEIGHT.get(v.sentiment, _DEFAULT_VISIT_WEIGHT)
        for cat in _cuisines(r):
            weights[cat] = weights.get(cat, 0.0) + w
        if w > 0 and r.price_level:
            prices.append(r.price_level)

    # Signal 2: per-item feedback on past recommendations.
    logs = db.scalars(
        select(models.RecommendationLog).where(
            models.RecommendationLog.user_id == user.id
        )
    ).all()
    for log in logs:
        for restaurant_id, events in (log.user_feedback or {}).items():
            r = db.get(models.Restaurant, restaurant_id)
            if r is None:
                continue
            for event in events:
                had_signal = True
                w = _ACTION_WEIGHT.get(event.get("action"), 0.0)
                for cat in _cuisines(r):
                    weights[cat] = weights.get(cat, 0.0) + w
                if w > 0 and r.price_level:
                    prices.append(r.price_level)

    old_cuisines = dict(profile.cuisines_preferred or {})
    old_price = list(profile.price_pref or [])
    if had_signal:
        # Reassign new objects so SQLAlchemy tracks the JSON columns as dirty.
        profile.cuisines_preferred = {
            k: round(v, 3) for k, v in weights.items() if v > 0
        }
        if prices:
            profile.price_pref = sorted(set(prices))

    # Regenerate the summary only when the derived signal actually changed — the
    # summary may be an LLM call, and refresh() runs on every visit/feedback.
    signal_changed = (
        (profile.cuisines_preferred or {}) != old_cuisines
        or (profile.price_pref or []) != old_price
        or not profile.derived_summary
    )
    if signal_changed:
        profile.derived_summary = build_summary(profile)

    profile.updated_at = models.utcnow()
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def build_summary(profile: models.TasteProfile) -> str:
    """LLM-generated taste summary (TDD §5.1), falling back to a deterministic
    template when no API key is set or the call fails."""
    llm = proto.summarize_taste_profile(
        {
            "cuisines_preferred": profile.cuisines_preferred or {},
            "price_pref": profile.price_pref or [],
            "dietary_restrictions": profile.dietary_restrictions or [],
            "ambiance_prefs": profile.ambiance_prefs or [],
        }
    )
    return llm or _template_summary(profile)


def _template_summary(profile: models.TasteProfile) -> str:
    parts = []
    cuisines = sorted(
        (profile.cuisines_preferred or {}).items(), key=lambda kv: kv[1], reverse=True
    )
    top = [c for c, _ in cuisines[:3]]
    if top:
        parts.append("Leans toward " + ", ".join(top))
    if profile.price_pref:
        parts.append("comfortable at " + "/".join("$" * p for p in sorted(profile.price_pref)))
    if profile.dietary_restrictions:
        parts.append("dietary: " + ", ".join(profile.dietary_restrictions))
    if profile.ambiance_prefs:
        parts.append("ambiance: " + ", ".join(profile.ambiance_prefs))
    return ("; ".join(parts) + ".") if parts else "(no preferences learned yet)"
