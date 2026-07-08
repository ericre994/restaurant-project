"""Notes & tags are per-user-per-restaurant now: they follow a restaurant across
every list it's in, and are editable directly via /restaurants/{id}/note."""


def _core(client, t):
    return next(l for l in client.get("/lists").json() if l["type"] == t)


def test_note_and_tags_shared_across_lists(client):
    want = _core(client, "want_to_try")
    custom = client.post("/lists", json={"name": "Faves", "type": "custom"}).json()

    # Annotate r1 while adding it to Want-to-Try.
    client.post(
        f"/lists/{want['id']}/items",
        json={"restaurant_id": "r1", "note": "great crust", "tags": ["pizza"]},
    )
    # Add the same restaurant to a custom list with no annotation of its own.
    client.post(f"/lists/{custom['id']}/items", json={"restaurant_id": "r1"})

    # The custom-list item shows the SAME note/tags — they belong to the restaurant.
    custom_item = client.get(f"/lists/{custom['id']}/items").json()[0]
    assert custom_item["note"] == "great crust"
    assert custom_item["tags"] == ["pizza"]

    # Editing from the custom list updates the annotation everywhere.
    client.patch(
        f"/lists/{custom['id']}/items/r1", json={"note": "amazing crust", "tags": ["pizza", "date"]}
    )
    want_item = client.get(f"/lists/{want['id']}/items").json()[0]
    assert want_item["note"] == "amazing crust"
    assert want_item["tags"] == ["pizza", "date"]


def test_source_stays_per_list_item(client):
    # Two fresh custom lists (additive — neither evicts) so each membership keeps
    # its own `source`, proving source did NOT move to the shared note.
    a = client.post("/lists", json={"name": "From friends", "type": "custom"}).json()
    b = client.post("/lists", json={"name": "IG saves", "type": "custom"}).json()

    client.post(f"/lists/{a['id']}/items", json={"restaurant_id": "r2", "source": "friend"})
    client.post(f"/lists/{b['id']}/items", json={"restaurant_id": "r2", "source": "Instagram"})

    item_a = next(i for i in client.get(f"/lists/{a['id']}/items").json() if i["restaurant_id"] == "r2")
    item_b = next(i for i in client.get(f"/lists/{b['id']}/items").json() if i["restaurant_id"] == "r2")
    assert item_a["source"] == "friend"
    assert item_b["source"] == "Instagram"


def test_note_endpoint_get_empty_then_put(client):
    empty = client.get("/restaurants/r3/note")
    assert empty.status_code == 200
    assert empty.json() == {"restaurant_id": "r3", "note": None, "tags": [], "updated_at": None}

    put = client.put("/restaurants/r3/note", json={"note": "cozy", "tags": ["diner", "cheap"]})
    assert put.status_code == 200, put.text
    assert put.json()["note"] == "cozy"
    assert put.json()["tags"] == ["diner", "cheap"]

    # Persists on a fresh read, and surfaces on any list the restaurant joins.
    assert client.get("/restaurants/r3/note").json()["note"] == "cozy"
    want = _core(client, "want_to_try")
    client.post(f"/lists/{want['id']}/items", json={"restaurant_id": "r3"})
    item = next(i for i in client.get(f"/lists/{want['id']}/items").json() if i["restaurant_id"] == "r3")
    assert item["tags"] == ["diner", "cheap"]


def test_note_partial_update_leaves_other_field(client):
    client.put("/restaurants/r1/note", json={"note": "n1", "tags": ["a"]})
    # Touch only tags — note must survive.
    client.put("/restaurants/r1/note", json={"tags": ["a", "b"]})
    body = client.get("/restaurants/r1/note").json()
    assert body["note"] == "n1"
    assert body["tags"] == ["a", "b"]


def test_note_endpoint_unknown_restaurant_404(client):
    assert client.get("/restaurants/nope/note").status_code == 404
    assert client.put("/restaurants/nope/note", json={"note": "x"}).status_code == 404
