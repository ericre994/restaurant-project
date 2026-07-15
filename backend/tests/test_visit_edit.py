"""PATCH/DELETE /visits/{id}: edit and delete a logged visit (owner-only)."""
from datetime import datetime, timedelta, timezone


def _log(client, rid="r1", **kw):
    r = client.post("/visits", json={"restaurant_id": rid, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_edit_visit_updates_fields(client):
    v = _log(client, "r1", sentiment="liked", user_rating=3, notes="ok")
    r = client.patch(
        f"/visits/{v['id']}",
        json={"sentiment": "loved", "user_rating": 5, "notes": "amazing"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sentiment"] == "loved"
    assert body["user_rating"] == 5
    assert body["notes"] == "amazing"


def test_edit_visit_can_clear_a_field(client):
    v = _log(client, "r2", notes="temp")
    r = client.patch(f"/visits/{v['id']}", json={"notes": None})
    assert r.status_code == 200
    assert r.json()["notes"] is None


def test_edit_visit_rejects_future_date_and_bad_sentiment(client):
    v = _log(client, "r3")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert client.patch(f"/visits/{v['id']}", json={"visited_at": tomorrow}).status_code == 422
    assert client.patch(f"/visits/{v['id']}", json={"sentiment": "meh"}).status_code == 422


def test_delete_visit_removes_it(client):
    v = _log(client, "r2")
    assert client.delete(f"/visits/{v['id']}").status_code == 204
    remaining = [x["id"] for x in client.get("/visits").json()]
    assert v["id"] not in remaining


def test_edit_or_delete_missing_visit_404(client):
    assert client.patch("/visits/nope", json={"notes": "x"}).status_code == 404
    assert client.delete("/visits/nope").status_code == 404


def test_cannot_touch_another_users_visit(client):
    v = _log(client, "r1")  # default dev user
    other = {"X-User-Id": "someone-else"}
    assert client.patch(f"/visits/{v['id']}", json={"notes": "x"}, headers=other).status_code == 404
    assert client.delete(f"/visits/{v['id']}", headers=other).status_code == 404
