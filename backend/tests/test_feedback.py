"""Tests for recommendation logging + the feedback loop (TDD §4.5)."""


def _make_recommendation(client):
    resp = client.post("/recommendations", json={"query": "tasty"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_recommendation_is_logged_with_provenance(client):
    rec = _make_recommendation(client)
    assert rec["recommendation_id"]

    log = client.get(f"/recommendations/{rec['recommendation_id']}").json()
    assert log["query_text"] == "tasty"
    assert log["prompt_version"]                      # from the prototype
    assert log["shown_restaurant_ids"]                # what the user saw
    assert log["candidate_set"]                       # ids + source
    assert log["context"]["taste_snapshot"] is not None
    assert log["latency_ms"] is not None
    assert log["user_feedback"] in (None, {})         # nothing yet


def test_feedback_roundtrip(client):
    rec = _make_recommendation(client)
    rec_id = rec["recommendation_id"]
    rid = rec["picks"][0]["restaurant_id"]

    resp = client.post(
        f"/recommendations/{rec_id}/feedback",
        json={"restaurant_id": rid, "action": "saved"},
    )
    assert resp.status_code == 200, resp.text

    log = client.get(f"/recommendations/{rec_id}").json()
    assert rid in log["user_feedback"]
    assert log["user_feedback"][rid][0]["action"] == "saved"

    # A second action on the same item accumulates rather than overwriting.
    client.post(
        f"/recommendations/{rec_id}/feedback",
        json={"restaurant_id": rid, "action": "thumbs_up"},
    )
    log = client.get(f"/recommendations/{rec_id}").json()
    actions = [e["action"] for e in log["user_feedback"][rid]]
    assert actions == ["saved", "thumbs_up"]


def test_feedback_rejects_unknown_action(client):
    rec = _make_recommendation(client)
    rid = rec["picks"][0]["restaurant_id"]
    resp = client.post(
        f"/recommendations/{rec['recommendation_id']}/feedback",
        json={"restaurant_id": rid, "action": "yum"},
    )
    assert resp.status_code == 422


def test_feedback_rejects_unshown_restaurant(client):
    rec = _make_recommendation(client)
    resp = client.post(
        f"/recommendations/{rec['recommendation_id']}/feedback",
        json={"restaurant_id": "not-a-candidate", "action": "saved"},
    )
    assert resp.status_code == 422


def test_feedback_on_unknown_recommendation_404(client):
    resp = client.post(
        "/recommendations/does-not-exist/feedback",
        json={"restaurant_id": "r1", "action": "saved"},
    )
    assert resp.status_code == 404
