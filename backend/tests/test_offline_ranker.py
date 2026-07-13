"""Unit tests for the personalized offline ranker (prototype `_heuristic_rank`).

These call the ranker directly (no LLM, no DB) to prove the offline path really
personalizes: the same candidate set is ordered differently for different taste
profiles, the query and price/feature signals bite, and every pick carries a
real 0-100 score plus at least one reason. This is the ranker the API serves
whenever the LLM is off (no ANTHROPIC_API_KEY), so it's the quality that ships
today.
"""
from app._proto import proto


def _cand(rid, name, categories, price, rating, rating_count, *,
          distance=None, outdoor=None, alcohol=None, takeout=None):
    rec = {
        "id": rid, "name": name, "categories": categories, "price_level": price,
        "rating": rating, "rating_count": rating_count,
        "outdoor_seating": outdoor, "alcohol": alcohol, "takeout": takeout,
        "address": "123 Test St",
    }
    if distance is not None:
        rec["distance_km"] = distance
    return rec


# No location on the constraints -> the distance component drops out; the ranker
# leans on cuisine/query/price/rating.
C = proto.Constraints(radius_km=4.0)

CANDIDATES = [
    _cand("ital", "Trattoria", ["Italian", "Wine Bars"], 3, 4.4, 300),
    _cand("sushi", "Omakase", ["Sushi", "Japanese"], 3, 4.6, 200),
    _cand("taco", "Taqueria", ["Mexican", "Tacos"], 1, 4.3, 400),
]


def _order(profile, query="dinner tonight"):
    picks = proto._heuristic_rank(CANDIDATES, profile, query, C)
    return [p["restaurant_id"] for p in picks]


def test_taste_profile_changes_ordering():
    """The single most important property: the same candidates rank differently
    for different diners. A rating sort (the old fallback) could never do this."""
    italian_lover = proto.TasteProfile(
        cuisines_preferred={"Italian": 1.0, "Wine Bars": 0.6}, price_pref=[2, 3]
    )
    taco_lover = proto.TasteProfile(
        cuisines_preferred={"Mexican": 1.0, "Tacos": 0.8}, price_pref=[1, 2]
    )
    assert _order(italian_lover)[0] == "ital"
    assert _order(taco_lover)[0] == "taco"


def test_picks_have_scores_and_reasons():
    profile = proto.TasteProfile(cuisines_preferred={"Italian": 1.0}, price_pref=[3])
    picks = proto._heuristic_rank(CANDIDATES, profile, "italian wine", C)
    assert picks
    for p in picks:
        assert isinstance(p["match_score"], int)
        assert 0 <= p["match_score"] <= 100
        assert p["reasons"], "every pick should carry at least one reason"
    assert picks[0]["restaurant_id"] == "ital"
    assert any("Italian" in reason for reason in picks[0]["reasons"])


def test_query_features_reward_matching_candidates():
    """Two identical-cuisine candidates; only one has outdoor seating. A query
    asking for a patio should surface the outdoor one."""
    neutral = proto.TasteProfile(cuisines_preferred={}, price_pref=[1, 2, 3])
    cands = [
        _cand("indoor", "Corner Cafe", ["Cafes"], 2, 4.4, 100),
        _cand("patio", "Garden Cafe", ["Cafes"], 2, 4.4, 100, outdoor=True),
    ]
    picks = proto._heuristic_rank(cands, neutral, "coffee on a patio outside", C)
    assert picks[0]["restaurant_id"] == "patio"
    assert any("outdoor" in reason for reason in picks[0]["reasons"])


def test_price_comfort_influences_ranking():
    """With cuisine/rating equal, the in-budget option wins."""
    budget = proto.TasteProfile(cuisines_preferred={}, price_pref=[1])
    cands = [
        _cand("cheap", "Budget Bites", ["Diner"], 1, 4.3, 200),
        _cand("pricey", "Fancy Diner", ["Diner"], 4, 4.3, 200),
    ]
    picks = proto._heuristic_rank(cands, budget, "dinner", C)
    assert picks[0]["restaurant_id"] == "cheap"


def test_cold_start_falls_back_to_quality():
    """No taste + a generic (all-stopword) query -> ranking driven by review
    quality, so the ranker degrades gracefully instead of ordering randomly."""
    cold = proto.TasteProfile()
    cands = [
        _cand("hi", "High Rated", ["Diner"], 2, 4.8, 500),
        _cand("lo", "Low Rated", ["Diner"], 2, 3.2, 500),
    ]
    picks = proto._heuristic_rank(cands, cold, "food", C)
    assert picks[0]["restaurant_id"] == "hi"


def test_low_volume_high_rating_does_not_dominate():
    """A 5.0 from 3 reviews should not outrank a 4.6 from 800 (volume shrink)."""
    cold = proto.TasteProfile()
    cands = [
        _cand("thin", "Three Reviews", ["Diner"], 2, 5.0, 3),
        _cand("proven", "Eight Hundred", ["Diner"], 2, 4.6, 800),
    ]
    picks = proto._heuristic_rank(cands, cold, "dinner", C)
    assert picks[0]["restaurant_id"] == "proven"
