"""Regression guard for the JSON-column in-place-mutation footgun (CLAUDE.md).

SQLAlchemy does NOT track in-place edits to a JSON column, so every write must
reassign a new object (`log.user_feedback = {...}`), not mutate the existing one.
This test exercises the append-to-existing-JSON shape that an in-place edit would
silently drop, then reads back through a *fresh request* (new DB session) so a
non-persisted update surfaces as a failure instead of being masked by the
identity map. `recommendation_logs.user_feedback` is the canonical case; the
tags and taste-profile write paths are covered the same way in
test_restaurant_notes.py and test_taste_profile.py.
"""


def test_user_feedback_append_persists_across_sessions(client):
    rec = client.post("/recommendations", json={"query": "anything"}).json()
    rec_id = rec["recommendation_id"]
    rid = rec["picks"][0]["restaurant_id"]

    # Two separate requests: the second APPENDS to the JSON the first wrote.
    for action in ("saved", "thumbs_up"):
        resp = client.post(
            f"/recommendations/{rec_id}/feedback",
            json={"restaurant_id": rid, "action": action},
        )
        assert resp.status_code == 200, resp.text

    # Fresh GET (new session): both events must survive. Under in-place mutation
    # the second write is never flagged dirty and would be lost right here.
    log = client.get(f"/recommendations/{rec_id}").json()
    assert [e["action"] for e in log["user_feedback"][rid]] == ["saved", "thumbs_up"]
