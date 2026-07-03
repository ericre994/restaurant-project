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


def test_rename_custom_list(client):
    created = client.post("/lists", json={"name": "Brunch", "type": "custom"})
    list_id = created.json()["id"]

    renamed = client.patch(f"/lists/{list_id}", json={"name": "Weekend Brunch"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Weekend Brunch"
    # The rename persists on a fresh read.
    got = next(l for l in client.get("/lists").json() if l["id"] == list_id)
    assert got["name"] == "Weekend Brunch"


def test_cannot_rename_core_list(client):
    want = next(l for l in client.get("/lists").json() if l["type"] == "want_to_try")
    resp = client.patch(f"/lists/{want['id']}", json={"name": "My Wishlist"})
    assert resp.status_code == 400


def test_edit_item_note_and_tags(client):
    want = next(l for l in client.get("/lists").json() if l["type"] == "want_to_try")
    client.post(
        f"/lists/{want['id']}/items",
        json={"restaurant_id": "r1", "note": "old note", "tags": ["pizza"]},
    )

    # Partial update: change tags, leave note untouched.
    resp = client.patch(
        f"/lists/{want['id']}/items/r1", json={"tags": ["pizza", "date-night"]}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tags"] == ["pizza", "date-night"]
    assert body["note"] == "old note"

    # Update the note too; new tag filter reflects the change.
    client.patch(f"/lists/{want['id']}/items/r1", json={"note": "great for two"})
    items = client.get(f"/lists/{want['id']}/items?tag=date-night").json()
    assert len(items) == 1
    assert items[0]["note"] == "great for two"


def test_edit_item_not_in_list_404(client):
    want = next(l for l in client.get("/lists").json() if l["type"] == "want_to_try")
    resp = client.patch(f"/lists/{want['id']}/items/nope", json={"note": "x"})
    assert resp.status_code == 404


def test_core_lists_are_mutually_exclusive(client):
    lists = {l["type"]: l for l in client.get("/lists").json()}
    want, visited = lists["want_to_try"], lists["visited"]

    # Save to Want-to-Try, then add the same restaurant to Visited.
    client.post(f"/lists/{want['id']}/items", json={"restaurant_id": "r1"})
    client.post(f"/lists/{visited['id']}/items", json={"restaurant_id": "r1"})

    want_ids = {i["restaurant_id"] for i in client.get(f"/lists/{want['id']}/items").json()}
    visited_ids = {i["restaurant_id"] for i in client.get(f"/lists/{visited['id']}/items").json()}
    assert "r1" not in want_ids, "adding to Visited should drop it from Want-to-Try"
    assert "r1" in visited_ids

    # And back the other way.
    client.post(f"/lists/{want['id']}/items", json={"restaurant_id": "r1"})
    want_ids = {i["restaurant_id"] for i in client.get(f"/lists/{want['id']}/items").json()}
    visited_ids = {i["restaurant_id"] for i in client.get(f"/lists/{visited['id']}/items").json()}
    assert "r1" in want_ids
    assert "r1" not in visited_ids


def test_custom_lists_stay_additive_with_core(client):
    want = next(l for l in client.get("/lists").json() if l["type"] == "want_to_try")
    custom = client.post("/lists", json={"name": "Faves", "type": "custom"}).json()

    client.post(f"/lists/{want['id']}/items", json={"restaurant_id": "r2"})
    client.post(f"/lists/{custom['id']}/items", json={"restaurant_id": "r2"})

    # A custom-list add does NOT evict it from the core list.
    want_ids = {i["restaurant_id"] for i in client.get(f"/lists/{want['id']}/items").json()}
    custom_ids = {i["restaurant_id"] for i in client.get(f"/lists/{custom['id']}/items").json()}
    assert "r2" in want_ids and "r2" in custom_ids


def test_visit_history_filtered_by_restaurant(client):
    # Log two visits to r3 and one to r1; the filter returns only r3's.
    client.post("/visits", json={"restaurant_id": "r3", "sentiment": "liked"})
    client.post("/visits", json={"restaurant_id": "r3", "sentiment": "loved"})
    client.post("/visits", json={"restaurant_id": "r1"})

    r3_visits = client.get("/visits?restaurant_id=r3").json()
    assert len(r3_visits) == 2
    assert {v["restaurant_id"] for v in r3_visits} == {"r3"}
