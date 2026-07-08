"""POST /visits must reject a visit dated after today (PRD fix-now)."""
from datetime import datetime, timedelta, timezone


def test_future_visit_rejected(client):
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    resp = client.post(
        "/visits", json={"restaurant_id": "r1", "visited_at": tomorrow.isoformat()}
    )
    assert resp.status_code == 422, resp.text
    assert "future" in resp.json()["detail"].lower()


def test_past_visit_allowed(client):
    last_week = datetime.now(timezone.utc) - timedelta(days=7)
    resp = client.post(
        "/visits", json={"restaurant_id": "r1", "visited_at": last_week.isoformat()}
    )
    assert resp.status_code == 201, resp.text


def test_visit_earlier_today_allowed(client):
    # A visit stamped at the very start of today (UTC) must pass even though the
    # current moment is later — the check compares calendar dates, not instants.
    start_of_today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    resp = client.post(
        "/visits", json={"restaurant_id": "r2", "visited_at": start_of_today.isoformat()}
    )
    assert resp.status_code == 201, resp.text


def test_visit_without_date_defaults_to_now(client):
    resp = client.post("/visits", json={"restaurant_id": "r3"})
    assert resp.status_code == 201, resp.text
