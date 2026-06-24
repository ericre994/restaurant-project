"""Tests for the taste_profiles table, the GET/PUT endpoints, and aggregation.

Each test uses a distinct X-User-Id so it gets an isolated profile + history,
independent of state other test files leave on the default dev user.
"""


def _h(uid):
    return {"X-User-Id": uid}


def test_taste_profile_starts_empty(client):
    p = client.get("/me/taste-profile", headers=_h("taste-empty")).json()
    assert p["cuisines_preferred"] == {}
    assert p["dietary_restrictions"] == []
    assert p["id"]


def test_put_sets_and_preserves_explicit_prefs(client):
    h = _h("taste-explicit")
    resp = client.put(
        "/me/taste-profile",
        headers=h,
        json={"dietary_restrictions": ["vegetarian"], "ambiance_prefs": ["quiet"]},
    )
    assert resp.status_code == 200, resp.text

    p = client.get("/me/taste-profile", headers=h).json()
    assert p["dietary_restrictions"] == ["vegetarian"]
    assert p["ambiance_prefs"] == ["quiet"]


def test_put_regenerates_summary_with_explicit_prefs(client, monkeypatch):
    # This asserts the *template* summary (which surfaces explicit ambiance/dietary
    # prefs), so pin template mode regardless of how the suite is invoked — the
    # fake LLM summary intentionally only references cuisines + price.
    monkeypatch.delenv("FAKE_LLM", raising=False)
    h = _h("taste-summary")
    client.put(
        "/me/taste-profile",
        headers=h,
        json={"ambiance_prefs": ["lively"], "dietary_restrictions": ["vegan"]},
    )
    p = client.get("/me/taste-profile", headers=h).json()
    assert "lively" in p["derived_summary"]
    assert "vegan" in p["derived_summary"]


def test_visit_aggregates_into_profile(client):
    h = _h("taste-visitor")
    client.post("/visits", headers=h, json={"restaurant_id": "r1", "sentiment": "loved"})

    p = client.get("/me/taste-profile", headers=h).json()
    # r1 is Pizza / Italian; a "loved" visit gives both positive weight.
    assert p["cuisines_preferred"].get("Pizza", 0) > 0
    assert p["cuisines_preferred"].get("Italian", 0) > 0
    assert "Pizza" in p["derived_summary"] or "Italian" in p["derived_summary"]


def test_aggregation_preserves_explicit_dietary(client):
    h = _h("taste-mixed")
    client.put("/me/taste-profile", headers=h, json={"dietary_restrictions": ["halal"]})
    client.post("/visits", headers=h, json={"restaurant_id": "r2", "sentiment": "liked"})

    p = client.get("/me/taste-profile", headers=h).json()
    assert p["dietary_restrictions"] == ["halal"]          # explicit pref preserved
    assert p["cuisines_preferred"].get("Sushi", 0) > 0     # derived from the visit


def test_recommendation_feedback_aggregates(client):
    h = _h("taste-feedback")
    rec = client.post("/recommendations", headers=h, json={"query": "anything"}).json()
    # r1 (Pizza) is among the shown candidates; a thumbs-up should lift Pizza.
    assert "r1" in rec_shown(rec)
    client.post(
        f"/recommendations/{rec['recommendation_id']}/feedback",
        headers=h,
        json={"restaurant_id": "r1", "action": "thumbs_up"},
    )

    p = client.get("/me/taste-profile", headers=h).json()
    assert p["cuisines_preferred"].get("Pizza", 0) > 0


def test_negative_feedback_does_not_add_preference(client):
    h = _h("taste-negative")
    rec = client.post("/recommendations", headers=h, json={"query": "anything"}).json()
    client.post(
        f"/recommendations/{rec['recommendation_id']}/feedback",
        headers=h,
        json={"restaurant_id": "r2", "action": "thumbs_down"},
    )

    p = client.get("/me/taste-profile", headers=h).json()
    # Sushi got only negative signal, so it must not appear as a preference.
    assert "Sushi" not in p["cuisines_preferred"]


def rec_shown(rec):
    return {pick["restaurant_id"] for pick in rec["picks"]}
