"""Tests for the restaurant lookup router: exact + fuzzy name search, the
cuisine-autocomplete endpoint, and the detail endpoint's attributes payload."""


def test_exact_substring_search(client):
    names = [r["name"] for r in client.get("/restaurants?q=pizza").json()]
    assert names == ["Pizza Place"]


def test_fuzzy_search_tolerates_typo(client):
    # "piza" is not a substring of any name, so this only matches via the
    # typo-tolerant fallback (SequenceMatcher ratio on the "pizza" word).
    names = [r["name"] for r in client.get("/restaurants?q=piza").json()]
    assert "Pizza Place" in names


def test_fuzzy_can_be_disabled(client):
    # With fuzzy off, a typo that isn't a substring returns nothing.
    assert client.get("/restaurants?q=piza&fuzzy=false").json() == []


def test_fuzzy_does_not_match_unrelated_short_words(client):
    # Regression: a 1-2 char name word must not act as a substring wildcard
    # (e.g. matching every restaurant). "xq" is close to nothing seeded.
    assert client.get("/restaurants?q=xq").json() == []


def test_cuisine_filter(client):
    names = [r["name"] for r in client.get("/restaurants?cuisine=japanese").json()]
    assert names == ["Sushi Spot"]


def test_cuisines_endpoint_counts(client):
    cuisines = client.get("/restaurants/cuisines").json()
    by_name = {c["name"]: c["count"] for c in cuisines}
    # Both pizza-tagged... only one here, but Italian + Pizza each appear once.
    assert by_name.get("Pizza") == 1
    assert by_name.get("Japanese") == 1
    # `q` filters case-insensitively.
    filtered = client.get("/restaurants/cuisines?q=sush").json()
    assert [c["name"] for c in filtered] == ["Sushi"]


def test_detail_endpoint_returns_attributes_key(client):
    r = client.get("/restaurants/r1")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Pizza Place"
    assert "attributes" in body            # present in the schema even when null
    assert client.get("/restaurants/does-not-exist").status_code == 404
