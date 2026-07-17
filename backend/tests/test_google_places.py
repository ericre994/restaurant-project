"""Offline tests for the Google Places (New) retrieval provider.

No API key and no network: the HTTP layer is stubbed with httpx.MockTransport,
so these verify the request we build, the seed-dict mapping, the exact-radius
refine, the deterministic pre-rank order, and error handling.
"""
import json

import httpx
import pytest

from app._proto import proto
from app.providers import google_places as gp

PHILLY = (39.9526, -75.1652)


def _client(handler):
    """An httpx.Client whose requests are answered by ``handler(request)``."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def _places_response(places):
    def handler(request):
        return httpx.Response(200, json={"places": places})

    return _client(handler)


# --------------------------------------------------------------------------
# request building
# --------------------------------------------------------------------------
def test_build_request_body_maps_all_constraints():
    c = proto.Constraints(near=PHILLY, radius_km=3.0, price_max=2, open_now=True)
    body = gp._build_request_body("late night noodles", c)

    assert body["textQuery"] == "late night noodles"
    assert body["includedType"] == "restaurant"
    assert body["maxResultCount"] == min(proto.CANDIDATE_CAP, 20)
    assert body["priceLevels"] == ["PRICE_LEVEL_INEXPENSIVE", "PRICE_LEVEL_MODERATE"]
    assert body["openNow"] is True
    circle = body["locationBias"]["circle"]
    assert circle["center"] == {"latitude": PHILLY[0], "longitude": PHILLY[1]}
    assert circle["radius"] == 3000.0


def test_build_request_body_defaults_and_radius_cap():
    # No filters set; radius over 50 km is clamped to Google's max.
    c = proto.Constraints(near=PHILLY, radius_km=100.0)
    body = gp._build_request_body("   ", c)
    assert body["textQuery"] == "restaurant"          # blank query -> fallback
    assert "priceLevels" not in body and "openNow" not in body
    assert body["locationBias"]["circle"]["radius"] == 50_000.0


# --------------------------------------------------------------------------
# place -> seed-dict mapping
# --------------------------------------------------------------------------
def test_map_place_matches_seed_shape():
    place = {
        "id": "ChIJ_test",
        "displayName": {"text": "Nom Wah", "languageCode": "en"},
        "formattedAddress": "1 Race St, Philadelphia, PA",
        "location": {"latitude": 39.9554, "longitude": -75.1555},
        "types": ["chinese_restaurant", "restaurant"],
        "primaryType": "chinese_restaurant",
        "rating": 4.4,
        "userRatingCount": 321,
        "priceLevel": "PRICE_LEVEL_MODERATE",
        "regularOpeningHours": {
            "periods": [
                {"open": {"day": 1, "hour": 11, "minute": 0},
                 "close": {"day": 1, "hour": 22, "minute": 30}},
            ]
        },
    }
    seed = gp._map_place(place)

    assert seed["id"] == "ChIJ_test"
    assert seed["source"] == "google_places"
    assert seed["name"] == "Nom Wah"
    assert seed["categories"] == ["chinese_restaurant", "restaurant"]
    assert seed["price_level"] == 2
    assert seed["rating"] == 4.4
    assert seed["rating_count"] == 321
    # GeoJSON Point is [lon, lat] — the order the pipeline's latlon() expects.
    assert seed["location"] == {"type": "Point", "coordinates": [-75.1555, 39.9554]}
    assert proto.latlon(seed) == (39.9554, -75.1555)
    assert seed["attributes"]["hours"] == {"Monday": "11:00-22:30"}
    assert seed["attributes"]["features"] == {}
    assert seed["address"] == "1 Race St, Philadelphia, PA"


@pytest.mark.parametrize(
    "place",
    [
        {"id": "x", "types": ["restaurant"]},                       # no location
        {"location": {"latitude": 1.0, "longitude": 2.0}},          # no id
    ],
)
def test_map_place_drops_unusable(place):
    assert gp._map_place(place) is None


def test_map_place_handles_missing_optional_fields():
    seed = gp._map_place({"id": "x", "location": {"latitude": 1.0, "longitude": 2.0}})
    assert seed["price_level"] is None
    assert seed["rating"] is None
    assert seed["attributes"]["hours"] == {}


# --------------------------------------------------------------------------
# retrieve(): end-to-end over a mocked response
# --------------------------------------------------------------------------
def _place(pid, rating, count, lat, lon):
    return {
        "id": pid,
        "displayName": {"text": pid},
        "location": {"latitude": lat, "longitude": lon},
        "types": ["restaurant"],
        "rating": rating,
        "userRatingCount": count,
    }


def test_retrieve_refines_radius_and_preranks():
    places = [
        _place("A", 4.5, 100, 39.9554, -75.1555),   # ~0.9 km from center
        _place("B", 4.8, 50, 39.9560, -75.1500),    # ~1.3 km from center
        _place("C", 5.0, 10, 40.4400, -80.0000),    # Pittsburgh — far outside 3 km
    ]
    c = proto.Constraints(near=PHILLY, radius_km=3.0)
    with _places_response(places) as client:
        out = gp.retrieve("noodles", c, api_key="TEST", client=client)

    # C dropped by the exact-radius refine; remainder ordered rating desc.
    assert [r["id"] for r in out] == ["B", "A"]


def test_retrieve_prerank_tiebreakers():
    # Equal ratings -> higher count first; equal count -> id ascending.
    places = [
        _place("b", 4.5, 10, *PHILLY),
        _place("a", 4.5, 10, *PHILLY),
        _place("c", 4.5, 99, *PHILLY),
    ]
    with _places_response(places) as client:
        out = gp.retrieve("x", proto.Constraints(), api_key="TEST", client=client)
    assert [r["id"] for r in out] == ["c", "a", "b"]


def test_retrieve_caps_at_candidate_cap():
    places = [_place(f"p{i}", 4.0, i, *PHILLY) for i in range(40)]
    with _places_response(places) as client:
        out = gp.retrieve("x", proto.Constraints(), api_key="TEST", client=client)
    assert len(out) == proto.CANDIDATE_CAP


def test_retrieve_sends_key_and_field_mask():
    seen = {}

    def handler(request):
        seen["key"] = request.headers.get("X-Goog-Api-Key")
        seen["mask"] = request.headers.get("X-Goog-FieldMask")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"places": []})

    with _client(handler) as client:
        gp.retrieve("tacos", proto.Constraints(price_max=1), api_key="SECRET", client=client)

    assert seen["key"] == "SECRET"
    assert "places.priceLevel" in seen["mask"]
    assert "reviews" not in seen["mask"]              # stays in the Enterprise tier
    assert seen["body"]["priceLevels"] == ["PRICE_LEVEL_INEXPENSIVE"]


# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------
def test_retrieve_missing_key_raises(monkeypatch):
    monkeypatch.delenv(gp.ENV_KEY, raising=False)
    with pytest.raises(gp.GooglePlacesError, match=gp.ENV_KEY):
        gp.retrieve("x", proto.Constraints(), api_key=None)


def test_retrieve_http_error_surfaces_status():
    def handler(request):
        return httpx.Response(403, json={"error": {"message": "PERMISSION_DENIED"}})

    with _client(handler) as client:
        with pytest.raises(gp.GooglePlacesError) as exc:
            gp.retrieve("x", proto.Constraints(), api_key="TEST", client=client)
    assert exc.value.status == 403
    assert "PERMISSION_DENIED" in str(exc.value)


# --------------------------------------------------------------------------
# get_details(): lazy refresh-on-read
# --------------------------------------------------------------------------
def test_get_details_maps_place_and_sends_details_mask():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("X-Goog-Api-Key")
        seen["mask"] = request.headers.get("X-Goog-FieldMask")
        return httpx.Response(200, json=_place("ChIJ_x", 4.6, 210, *PHILLY))

    with _client(handler) as client:
        seed = gp.get_details("ChIJ_x", api_key="SECRET", client=client)

    assert seen["url"].endswith("/v1/places/ChIJ_x")   # place_id in the path
    assert seen["key"] == "SECRET"
    # Details mask uses bare field names (no "places." prefix) and stays Enterprise.
    assert "rating" in seen["mask"] and "places." not in seen["mask"]
    assert "reviews" not in seen["mask"]
    assert seed["id"] == "ChIJ_x" and seed["rating"] == 4.6
    assert seed["source"] == "google_places"


def test_get_details_404_raises_with_status():
    def handler(request):
        return httpx.Response(404, json={"error": {"message": "NOT_FOUND"}})

    with _client(handler) as client:
        with pytest.raises(gp.GooglePlacesError) as exc:
            gp.get_details("dead_id", api_key="TEST", client=client)
    assert exc.value.status == 404


def test_get_details_missing_key_raises(monkeypatch):
    monkeypatch.delenv(gp.ENV_KEY, raising=False)
    with pytest.raises(gp.GooglePlacesError, match=gp.ENV_KEY):
        gp.get_details("x", api_key=None)
