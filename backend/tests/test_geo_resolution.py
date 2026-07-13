"""Backend wiring for ZIP / neighborhood resolution on POST /recommendations.

The resolver is built from the restaurants in the DB (ZIP parsed off each
address). conftest seeds r1/r2 in Philadelphia ZIP 19107 and r3 in Pittsburgh
15213, so a ZIP or neighborhood in center-city Philadelphia surfaces the Philly
pair and excludes the far decoy.
"""
PHILLY = {"r1", "r2"}


def test_zip_code_resolves_to_local_candidates(client):
    resp = client.post(
        "/recommendations", json={"query": "dinner", "near": "19107", "radius_km": 3.0}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidate_count"] == 2
    assert {p["restaurant_id"] for p in body["picks"]} == PHILLY


def test_neighborhood_name_resolves_to_local_candidates(client):
    # chinatown -> 19107 (present in the test DB) -> the Philly pair.
    resp = client.post(
        "/recommendations", json={"query": "dinner", "near": "chinatown", "radius_km": 3.0}
    )
    assert resp.status_code == 200, resp.text
    assert {p["restaurant_id"] for p in resp.json()["picks"]} == PHILLY


def test_far_zip_excludes_philadelphia(client):
    # 15213 (Pittsburgh) resolves to r3 only; the Philly pair is out of radius.
    resp = client.post(
        "/recommendations", json={"query": "dinner", "near": "15213", "radius_km": 3.0}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {p["restaurant_id"] for p in body["picks"]} == {"r3"}
