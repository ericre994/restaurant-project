"""Tests for POST /recommendations.

These assert structural correctness that holds in BOTH llm and fallback modes,
so they pass whether or not an ANTHROPIC_API_KEY is present. Fixtures: r1/r2 are
~0.5 km apart in Philadelphia; r3 is a far-away decoy (see conftest).
"""

ALL_IDS = {"r1", "r2", "r3"}
PHILLY_IDS = {"r1", "r2"}
# A point right next to r1, used to exercise the geo filter.
NEAR_R1 = {"lat": 39.9554, "lng": -75.1555}


def test_recommendations_returns_ranked_candidates(client):
    resp = client.post("/recommendations", json={"query": "something tasty"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["candidate_count"] == 3
    assert body["picks"], "expected at least one pick"
    for pick in body["picks"]:
        # Hallucination guard: every pick maps to a real candidate.
        assert pick["restaurant_id"] in ALL_IDS
        assert pick["restaurant"]["id"] == pick["restaurant_id"]


def test_unknown_landmark_is_rejected(client):
    resp = client.post(
        "/recommendations", json={"query": "dinner", "near": "atlantis"}
    )
    assert resp.status_code == 422
    assert "unknown landmark" in resp.text


def test_price_filter_narrows_candidates(client):
    # r1=$$, r2=$$$, r3=$. Capping at 2 drops r2 (in SQL).
    resp = client.post("/recommendations", json={"query": "cheap", "price_max": 2})
    assert resp.status_code == 200, resp.text
    ids = {p["restaurant_id"] for p in resp.json()["picks"]}
    assert resp.json()["candidate_count"] == 2
    assert ids <= {"r1", "r3"}
    assert "r2" not in ids


def test_geo_filter_excludes_far_restaurants(client):
    # A 2 km radius around r1 includes r1 + r2 but not the far decoy r3.
    resp = client.post(
        "/recommendations",
        json={"query": "near me", "radius_km": 2.0, **NEAR_R1},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {p["restaurant_id"] for p in body["picks"]}
    assert body["candidate_count"] == 2
    assert ids == PHILLY_IDS


def test_cuisine_filter_runs_in_sql(client):
    resp = client.post(
        "/recommendations", json={"query": "raw fish", "cuisine": ["sushi"]}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidate_count"] == 1
    assert body["picks"][0]["restaurant_id"] == "r2"
