"""Offline tests for the Google Geocoding provider (httpx MockTransport)."""
import httpx
import pytest

from app.providers import google_geocoding as gc


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_geocode_returns_coords_and_biases_to_nyc():
    seen = {}

    def handler(request):
        seen["address"] = request.url.params.get("address")
        seen["key"] = request.url.params.get("key")
        return httpx.Response(
            200,
            json={"status": "OK", "results": [{"geometry": {"location": {"lat": 40.71, "lng": -73.99}}}]},
        )

    with _client(handler) as client:
        out = gc.geocode("chinatown", api_key="SECRET", client=client)

    assert out == (40.71, -73.99)
    assert seen["address"] == "chinatown, New York, NY"  # market bias appended
    assert seen["key"] == "SECRET"


def test_geocode_does_not_double_append_new_york():
    seen = {}

    def handler(request):
        seen["address"] = request.url.params.get("address")
        return httpx.Response(
            200, json={"status": "OK", "results": [{"geometry": {"location": {"lat": 1, "lng": 2}}}]}
        )

    with _client(handler) as client:
        gc.geocode("10001, New York, NY", api_key="K", client=client)
    assert seen["address"] == "10001, New York, NY"


def test_geocode_zero_results_returns_none():
    with _client(lambda r: httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []})) as client:
        assert gc.geocode("nowhere-xyz", api_key="K", client=client) is None


def test_geocode_error_status_raises():
    def handler(request):
        return httpx.Response(200, json={"status": "REQUEST_DENIED", "error_message": "bad key"})

    with _client(handler) as client:
        with pytest.raises(gc.GeocodingError, match="REQUEST_DENIED"):
            gc.geocode("x", api_key="K", client=client)


def test_geocode_missing_key_raises(monkeypatch):
    monkeypatch.delenv(gc.ENV_KEY, raising=False)
    with pytest.raises(gc.GeocodingError, match=gc.ENV_KEY):
        gc.geocode("x", api_key=None)


def test_geocode_blank_returns_none_without_calling_out():
    # Blank short-circuits before key resolution, so no key needed.
    assert gc.geocode("   ", api_key=None) is None
