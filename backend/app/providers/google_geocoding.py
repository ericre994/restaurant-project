"""Google Geocoding API — free-text `near=` -> (lat, lon) fallback.

The last layer of location resolution (recommender._resolve_location): when a
`near` value isn't a cached ZIP centroid or a curated NYC neighborhood, geocode it.
Biased to New York so a bare neighborhood/ZIP resolves within the launch market.

Cost: Geocoding is ~$5 / 1,000 with a 10k/mo free tier (session-6 model) — cheap,
and only hit on a cache/curated miss. Uses the same ``GOOGLE_MAPS_API_KEY`` (the
dev key is restricted to Places API New + Geocoding).

Auth/key handling mirrors the Places provider; ``client`` is injectable for
offline testing with an httpx MockTransport.
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

import httpx

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
ENV_KEY = "GOOGLE_MAPS_API_KEY"

#: Appended to a bare query so results land in the launch market. "chinatown" is
#: ambiguous nationwide; "chinatown, New York, NY" is not. Skipped if the caller
#: already spelled out New York.
_MARKET_SUFFIX = ", New York, NY"


class GeocodingError(RuntimeError):
    """Raised when geocoding can't run or the API errors (carries HTTP ``status``
    when available). A genuine no-match is NOT an error — it returns None."""

    def __init__(self, message: str, *, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


def _resolve_api_key(api_key: Optional[str]) -> str:
    key = api_key or os.getenv(ENV_KEY)
    if not key:
        raise GeocodingError(
            f"{ENV_KEY} is not set. Add it to backend/.env (see .env.example) or "
            f"export it. The key must have the Geocoding API enabled."
        )
    return key


def _market_query(text: str) -> str:
    t = text.strip()
    return t if "new york" in t.lower() or ", ny" in t.lower() else t + _MARKET_SUFFIX


def geocode(
    text: str,
    *,
    api_key: Optional[str] = None,
    client: Optional[httpx.Client] = None,
    timeout: float = 10.0,
) -> Optional[Tuple[float, float]]:
    """Geocode `text` to (lat, lon), biased to NYC. Returns None on no match;
    raises ``GeocodingError`` on a missing key or an API/transport error."""
    if not text or not text.strip():
        return None
    key = _resolve_api_key(api_key)
    params = {"address": _market_query(text), "key": key}

    owns_client = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        resp = client.get(GEOCODE_URL, params=params)
    except httpx.HTTPError as exc:
        raise GeocodingError(f"Geocoding request failed: {exc}") from exc
    finally:
        if owns_client:
            client.close()

    if resp.status_code != 200:
        raise GeocodingError(
            f"Geocoding returned HTTP {resp.status_code}", status=resp.status_code
        )

    body = resp.json()
    status = body.get("status")
    if status == "ZERO_RESULTS":
        return None
    if status != "OK":
        # REQUEST_DENIED / OVER_QUERY_LIMIT / INVALID_REQUEST etc.
        raise GeocodingError(f"Geocoding status {status}: {body.get('error_message', '')}")

    results = body.get("results") or []
    if not results:
        return None
    loc = ((results[0].get("geometry") or {}).get("location")) or {}
    lat, lng = loc.get("lat"), loc.get("lng")
    if lat is None or lng is None:
        return None
    return (lat, lng)
