"""Google Places API (New) — Stage-1 retrieval provider.

Implements the "retrieve" stage of the recommendation pipeline against the live
Google Places **Text Search (New)** endpoint, as a drop-in alternative to the
Yelp-seed / SQL path in ``recommender._sql_retrieve``. It returns the identical
*seed-dict* shape (see ``recommender._to_seed_dict``), so the prototype's
compact/rank/render stages consume its output unchanged.

Cost design (see the Google Maps integration plan / TDD §4.1):

* **One billable call per query.** A single ``places:searchText`` returns up to
  20 candidates — never fan out to per-place Detail calls at retrieval time.
* **Enterprise field mask, and no higher.** The field mask (``FIELD_MASK``)
  requests exactly the fields the ranker needs — rating, userRatingCount,
  priceLevel, regularOpeningHours — which lands the call in the **Enterprise**
  SKU tier (~$35 / 1,000). Adding ``reviews`` or ``editorialSummary`` would push
  the whole call to Enterprise+Atmosphere ($40) for no ranking benefit, so those
  are deliberately excluded and fetched lazily via Place Details only when a user
  opens a specific restaurant.

Hard filters are pushed into the request where Google supports them (price band,
open-now, ``includedType=restaurant``, a location-bias circle). The exact
circular radius is refined in Python with the prototype's ``haversine_km`` — the
same coarse-filter-then-refine pattern ``_sql_retrieve`` uses for its geo bbox —
because Text Search's location bias is a soft signal, not a hard cutoff.

Wired into ``recommender.recommend`` behind the ``RECS_PROVIDER`` toggle
(``seed`` default | ``google``): ``recommender._retrieve_candidates`` calls this
``retrieve`` when ``google`` is selected and falls back to the SQL/seed path on
any ``GooglePlacesError`` so the user always gets results. Still open, and
independent of the toggle: whether Google becomes the *default* live source, and
how/whether to cache Google content into the ``restaurants`` table (Google ToS
lets you store ``place_id`` indefinitely but restricts caching other content) —
see the integration plan.

Auth: reads ``GOOGLE_MAPS_API_KEY`` from the environment (loaded from
``backend/.env`` by ``app/__init__.py``). The key must be restricted to the
Places API (New).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .._proto import proto

SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places/"  # + place_id

#: Enterprise-tier field mask — the ranker's fields, and nothing that would bump
#: the call to the pricier Atmosphere tier. Keep in sync with ``_map_place``.
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.types",
        "places.primaryType",
        "places.rating",
        "places.userRatingCount",
        "places.priceLevel",
        "places.regularOpeningHours",
    ]
)

#: Place Details returns a single (unwrapped) place, so its field mask uses the
#: bare field names — the same set as FIELD_MASK without the ``places.`` prefix.
DETAILS_FIELD_MASK = ",".join(f.split("places.", 1)[-1] for f in FIELD_MASK.split(","))

ENV_KEY = "GOOGLE_MAPS_API_KEY"

#: Text Search caps a single response at 20 results; the pipeline cap is smaller.
_MAX_RESULT_COUNT = min(proto.CANDIDATE_CAP, 20)

#: Google's location-bias circle radius must be <= 50 km.
_MAX_RADIUS_M = 50_000.0

# Google priceLevel enum <-> the seed's integer 1..4 scale.
_PRICE_ENUM_TO_INT: Dict[str, int] = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}
_INT_TO_PRICE_ENUM: Dict[int, str] = {
    1: "PRICE_LEVEL_INEXPENSIVE",
    2: "PRICE_LEVEL_MODERATE",
    3: "PRICE_LEVEL_EXPENSIVE",
    4: "PRICE_LEVEL_VERY_EXPENSIVE",
}

# Google weekday: 0 = Sunday .. 6 = Saturday. Names match datetime.strftime("%A"),
# which is what the prototype's is_open_at() keys hours on.
_WEEKDAY_NAMES = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
]


class GooglePlacesError(RuntimeError):
    """Raised when the Places API call cannot be made or returns an error.

    Carries the HTTP ``status`` when one is available so callers can decide
    whether to fall back to another retrieval path.
    """

    def __init__(self, message: str, *, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


def _resolve_api_key(api_key: Optional[str]) -> str:
    key = api_key or os.getenv(ENV_KEY)
    if not key:
        raise GooglePlacesError(
            f"{ENV_KEY} is not set. Add it to backend/.env (see .env.example) or "
            f"export it in the shell. The key must be restricted to Places API (New)."
        )
    return key


def _build_request_body(query: str, c: "proto.Constraints") -> Dict[str, Any]:
    """Translate a text query + Constraints into a searchText request body.

    Filters Google can enforce server-side go here; the exact radius is refined
    in Python afterward. Cuisine is expressed through the natural-language query
    itself — Text Search has no structured cuisine filter — so callers should
    fold cuisine into ``query`` (the prototype's NL queries already do).
    """
    body: Dict[str, Any] = {
        "textQuery": query.strip() or "restaurant",
        "includedType": "restaurant",
        "maxResultCount": _MAX_RESULT_COUNT,
    }
    if c.price_max is not None:
        levels = [_INT_TO_PRICE_ENUM[i] for i in range(1, c.price_max + 1) if i in _INT_TO_PRICE_ENUM]
        if levels:
            body["priceLevels"] = levels
    if c.open_now:
        body["openNow"] = True
    if c.near is not None:
        lat, lon = c.near
        body["locationBias"] = {
            "circle": {
                "center": {"latitude": lat, "longitude": lon},
                "radius": min(c.radius_km * 1000.0, _MAX_RADIUS_M),
            }
        }
    return body


def _map_opening_hours(regular: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Google regularOpeningHours -> the seed's ``{Weekday: "HH:MM-HH:MM"}`` shape.

    Best-effort: takes the first period per opening day. Days with no close time
    (e.g. 24-hour venues) are skipped, which the prototype's is_open_at() reads as
    "hours unknown -> don't exclude". Only used when the app filters open-hours
    offline; live calls pass ``openNow`` to Google instead.
    """
    hours: Dict[str, str] = {}
    for period in (regular or {}).get("periods", []) or []:
        open_ = period.get("open") or {}
        close_ = period.get("close") or {}
        day = open_.get("day")
        if day is None or "hour" not in close_:
            continue
        name = _WEEKDAY_NAMES[day % 7]
        if name in hours:  # keep the first period for the day
            continue
        span = (
            f"{open_.get('hour', 0):02d}:{open_.get('minute', 0):02d}"
            f"-{close_.get('hour', 0):02d}:{close_.get('minute', 0):02d}"
        )
        hours[name] = span
    return hours


def _map_place(place: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One Google place -> a pipeline seed dict, or None if it can't be used.

    Mirrors ``recommender._to_seed_dict`` exactly: ``place_id`` is the stable
    ``id``, ``location`` is a GeoJSON Point ``[lon, lat]``, and ``attributes`` is
    ``{"features": {...}, "hours": {...}}``. ``features`` is empty because those
    signals (outdoor seating, alcohol, ...) live in the Atmosphere SKU tier, which
    the Enterprise field mask intentionally skips.
    """
    place_id = place.get("id")
    loc = place.get("location") or {}
    lat, lon = loc.get("latitude"), loc.get("longitude")
    if not place_id or lat is None or lon is None:
        return None

    price_enum = place.get("priceLevel")
    return {
        "id": place_id,
        "source": "google_places",
        "name": (place.get("displayName") or {}).get("text"),
        "categories": place.get("types") or [],
        "price_level": _PRICE_ENUM_TO_INT.get(price_enum) if price_enum else None,
        "rating": place.get("rating"),
        "rating_count": place.get("userRatingCount"),
        "location": {"type": "Point", "coordinates": [lon, lat]},
        "attributes": {
            "features": {},
            "hours": _map_opening_hours(place.get("regularOpeningHours")),
        },
        "address": place.get("formattedAddress"),
        "raw": place,  # full provider payload, retained for the write-through cache
    }


def _prerank_key(seed: Dict[str, Any]) -> Tuple[float, float, str]:
    # Match _sql_retrieve / prototype retrieve(): rating desc, count desc, id asc.
    return (-(seed.get("rating") or 0.0), -(seed.get("rating_count") or 0), str(seed.get("id")))


def retrieve(
    query: str,
    constraints: "proto.Constraints",
    *,
    api_key: Optional[str] = None,
    client: Optional[httpx.Client] = None,
    timeout: float = 10.0,
) -> List[Dict[str, Any]]:
    """Stage 1 against Google Text Search: one call -> capped seed dicts.

    Returns candidates in the same deterministic pre-rank order the rest of the
    pipeline expects (rating desc, rating_count desc, id asc), capped at
    ``CANDIDATE_CAP``. Raises ``GooglePlacesError`` on a missing key or an API
    error so the caller can fall back to another retrieval path.

    ``client`` is injectable for testing (pass an ``httpx.Client`` with a mock
    transport); by default a short-lived client is created per call.
    """
    key = _resolve_api_key(api_key)
    body = _build_request_body(query, constraints)
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": FIELD_MASK,
    }

    owns_client = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        resp = client.post(SEARCH_TEXT_URL, headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise GooglePlacesError(f"Places request failed: {exc}") from exc
    finally:
        if owns_client:
            client.close()

    if resp.status_code != 200:
        # Google returns {"error": {"message": ...}} on failures.
        detail = ""
        try:
            detail = (resp.json().get("error") or {}).get("message", "")
        except ValueError:
            detail = resp.text[:200]
        raise GooglePlacesError(
            f"Places API returned {resp.status_code}: {detail}", status=resp.status_code
        )

    places = resp.json().get("places", []) or []
    seed = [m for m in (_map_place(p) for p in places) if m is not None]

    # Text Search's location bias is soft; enforce the exact radius like the SQL
    # path refines its bbox.
    if constraints.near is not None:
        seed = [
            s
            for s in seed
            if proto.haversine_km(constraints.near, proto.latlon(s)) <= constraints.radius_km
        ]

    seed.sort(key=_prerank_key)
    return seed[: proto.CANDIDATE_CAP]


def get_details(
    place_id: str,
    *,
    api_key: Optional[str] = None,
    client: Optional[httpx.Client] = None,
    timeout: float = 10.0,
) -> Optional[Dict[str, Any]]:
    """Fetch one place via **Place Details (New)** and map it to a seed dict.

    Used for lazy refresh-on-read: when a cached row is past its TTL, one Details
    call refreshes just that place (the cost-optimal pattern — no fan-out). Uses
    the same Enterprise field set as the search path, so the refreshed row carries
    the same fields. Returns None if the payload is unusable; raises
    ``GooglePlacesError`` (``status`` set) on a missing key or an API error — a
    404 means the place_id is gone.

    ``client`` is injectable for testing (an ``httpx.Client`` with a mock
    transport); by default a short-lived client is created per call.
    """
    key = _resolve_api_key(api_key)
    headers = {
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": DETAILS_FIELD_MASK,
    }

    owns_client = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        resp = client.get(PLACE_DETAILS_URL + place_id, headers=headers)
    except httpx.HTTPError as exc:
        raise GooglePlacesError(f"Place Details request failed: {exc}") from exc
    finally:
        if owns_client:
            client.close()

    if resp.status_code != 200:
        detail = ""
        try:
            detail = (resp.json().get("error") or {}).get("message", "")
        except ValueError:
            detail = resp.text[:200]
        raise GooglePlacesError(
            f"Place Details returned {resp.status_code}: {detail}", status=resp.status_code
        )

    return _map_place(resp.json())


def _main(argv: Optional[List[str]] = None) -> int:
    """Tiny smoke CLI: make one real Text Search call and print the candidates.

        python -m app.providers.google_places "late night noodles, casual" \
            --near-lat 39.9526 --near-lng -75.1652 --price-max 2 --radius-km 3
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Google Places Text Search smoke test")
    parser.add_argument("query")
    parser.add_argument("--near-lat", type=float, default=None)
    parser.add_argument("--near-lng", type=float, default=None)
    parser.add_argument("--radius-km", type=float, default=proto.DEFAULT_RADIUS_KM)
    parser.add_argument("--price-max", type=int, default=None)
    parser.add_argument("--open-now", action="store_true")
    args = parser.parse_args(argv)

    near = (
        (args.near_lat, args.near_lng)
        if args.near_lat is not None and args.near_lng is not None
        else None
    )
    constraints = proto.Constraints(
        near=near,
        radius_km=args.radius_km,
        price_max=args.price_max,
        open_now=args.open_now,
    )
    try:
        results = retrieve(args.query, constraints)
    except GooglePlacesError as exc:
        print(f"error: {exc}")
        return 1

    print(f"{len(results)} candidate(s):")
    for r in results:
        price = "$" * (r["price_level"] or 0) or "?"
        print(
            f"  {r['rating']}★ ({r['rating_count']}) {price:5} {r['name']}"
            f"  [{r['id']}]"
        )
    print(json.dumps(results[:1], indent=2))  # full shape of one candidate
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
