"""End-to-end tests for the list-management capability via the HTTP layer."""


def test_core_lists_autocreated(client):
    resp = client.get("/lists")
    assert resp.status_code == 200
    types = {lst["type"] for lst in resp.json()}
    assert {"want_to_try", "visited"} <= types


def test_add_list_and_remove_item(client):
    want = next(l for l in client.get("/lists").json() if l["type"] == "want_to_try")

    added = client.post(
        f"/lists/{want['id']}/items",
        json={"restaurant_id": "r1", "tags": ["pizza"], "source": "Instagram"},
    )
    assert added.status_code == 201, added.text
    assert added.json()["restaurant"]["name"] == "Pizza Place"

    # Same restaurant twice in one list -> 409 (UNIQUE(list_id, restaurant_id)).
    dup = client.post(f"/lists/{want['id']}/items", json={"restaurant_id": "r1"})
    assert dup.status_code == 409

    # Tag filter finds it; a non-matching tag does not.
    assert len(client.get(f"/lists/{want['id']}/items?tag=pizza").json()) == 1
    assert client.get(f"/lists/{want['id']}/items?tag=sushi").json() == []

    assert client.delete(f"/lists/{want['id']}/items/r1").status_code == 204
    assert client.get(f"/lists/{want['id']}/items").json() == []


def test_recording_visit_moves_restaurant_to_visited(client):
    lists = {l["type"]: l for l in client.get("/lists").json()}
    want, visited = lists["want_to_try"], lists["visited"]

    client.post(f"/lists/{want['id']}/items", json={"restaurant_id": "r2"})
    visit = client.post(
        "/visits",
        json={"restaurant_id": "r2", "sentiment": "loved", "user_rating": 5},
    )
    assert visit.status_code == 201, visit.text

    want_ids = {i["restaurant_id"] for i in client.get(f"/lists/{want['id']}/items").json()}
    visited_ids = {i["restaurant_id"] for i in client.get(f"/lists/{visited['id']}/items").json()}
    assert "r2" not in want_ids
    assert "r2" in visited_ids


def test_invalid_sentiment_rejected(client):
    bad = client.post("/visits", json={"restaurant_id": "r1", "sentiment": "meh"})
    assert bad.status_code == 422


def test_custom_list_create_and_delete(client):
    created = client.post("/lists", json={"name": "Date Night", "type": "custom"})
    assert created.status_code == 201
    list_id = created.json()["id"]
    assert client.delete(f"/lists/{list_id}").status_code == 204


def test_cannot_delete_core_list(client):
    want = next(l for l in client.get("/lists").json() if l["type"] == "want_to_try")
    assert client.delete(f"/lists/{want['id']}").status_code == 400
