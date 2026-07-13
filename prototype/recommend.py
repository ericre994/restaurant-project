#!/usr/bin/env python3
"""
Recommendation pipeline prototype
==================================
Validates the core technical bet from the design doc: retrieve -> rank -> render.

  Stage 1  Retrieve   : hard-filter the seed to a small candidate set (<=20)
  Stage 2  Rank        : LLM ranks/explains ONLY those candidates (strict JSON)
  Stage 3  Render      : validate, hallucination-guard, hydrate, print cards

No database. Runs entirely against the Philadelphia seed JSON so we can judge
whether the recommendations *feel* right before building any infrastructure.

Usage
-----
  pip install anthropic
  export ANTHROPIC_API_KEY=sk-ant-...
  python recommend.py --demo date_night
  python recommend.py --query "cheap late-night ramen near Chinatown, casual"

If no API key is set (or the call fails), it falls back to a rating-sorted
list so you still see the retrieval stage working.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
SEED_PATH = (
    Path(__file__).resolve().parent.parent
    / "YelpData" / "output" / "restaurants_Philadelphia_schema.json"
)
MODEL = "claude-sonnet-4-6"
PROMPT_VERSION = "proto-v1"
CANDIDATE_CAP = 18          # design doc: 15-20
DEFAULT_RADIUS_KM = 4.0

# A few neighborhood centroids so --near works even with no seed loaded. These
# are a static fallback: when the seed (or DB) is available, the GeoIndex below
# supersedes them with centroids derived from the data and far broader coverage.
LANDMARKS = {
    "chinatown":       (39.9554, -75.1555),
    "center city":     (39.9518, -75.1652),
    "rittenhouse":     (39.9495, -75.1718),
    "fishtown":        (39.9707, -75.1349),
    "south philly":    (39.9300, -75.1600),
    "university city": (39.9522, -75.1932),
    "old city":        (39.9510, -75.1436),
}


# --------------------------------------------------------------------------
# Neighborhood / ZIP resolution, derived from the data (no geocoding service)
# --------------------------------------------------------------------------
# The seed carries no neighborhood field, but every address ends in a ZIP and
# every row has exact coordinates. So we resolve a place name to a search center
# by averaging the coordinates of the seed restaurants in the relevant ZIP(s):
#   - a bare 5-digit ZIP  -> that ZIP's restaurant centroid (all 56 covered);
#   - a known neighborhood -> the centroid of its ZIPs (coords DATA-DERIVED, not
#     hardcoded), via the small extensible NEIGHBORHOOD_ZIPS table below;
#   - a near-miss name     -> fuzzy-matched to the closest neighborhood;
#   - anything else        -> unresolved (caller reports the known names).
_ZIP_RE = re.compile(r"(\d{5})(?:-\d{4})?\s*\Z")


def zip_of(address: str | None) -> str | None:
    """The 5-digit ZIP at the end of an address, or None."""
    m = _ZIP_RE.search((address or "").strip())
    return m.group(1) if m else None


# Well-known Philadelphia neighborhoods -> the ZIP(s) they span. Small,
# extensible reference data; the coordinates come from the data. The index drops
# any alias whose ZIPs are absent from the current dataset, so this table may
# safely list more than a given seed contains.
NEIGHBORHOOD_ZIPS = {
    "chinatown": ["19107"],
    "center city": ["19102", "19103", "19107"],
    "rittenhouse": ["19103", "19102"],
    "washington square west": ["19107"],
    "old city": ["19106"],
    "society hill": ["19106"],
    "northern liberties": ["19123"],
    "fishtown": ["19125"],
    "kensington": ["19134", "19125"],
    "port richmond": ["19134"],
    "fairmount": ["19130"],
    "spring garden": ["19130", "19123"],
    "brewerytown": ["19121"],
    "university city": ["19104"],
    "west philadelphia": ["19104", "19139", "19143"],
    "queen village": ["19147"],
    "bella vista": ["19147"],
    "south philadelphia": ["19147", "19148", "19145", "19146"],
    "south philly": ["19147", "19148", "19145", "19146"],
    "graduate hospital": ["19146"],
    "point breeze": ["19146", "19145"],
    "east passyunk": ["19148"],
    "passyunk": ["19148"],
    "manayunk": ["19127"],
    "roxborough": ["19128"],
    "chestnut hill": ["19118"],
    "mount airy": ["19119"],
    "germantown": ["19144"],
}


class GeoIndex:
    """ZIP-centroid + neighborhood resolver built from a dataset's points."""

    def __init__(self, zip_centroids: dict, neighborhoods: dict):
        self.zip_centroids = zip_centroids      # {"19107": (lat, lon), ...}
        self.neighborhoods = neighborhoods      # {"chinatown": (lat, lon), ...}

    def resolve(self, name: str) -> tuple | None:
        """Resolve a ZIP or neighborhood name to a (lat, lon) search center."""
        key = (name or "").strip().lower()
        if not key:
            return None
        z = zip_of(key)
        if z and z in self.zip_centroids:
            return self.zip_centroids[z]
        if key in self.neighborhoods:
            return self.neighborhoods[key]
        match = _closest_name(key, self.neighborhoods)
        return self.neighborhoods[match] if match else None

    @property
    def place_names(self) -> list:
        """Resolvable neighborhood names (any of the 5-digit ZIPs also work)."""
        return sorted(self.neighborhoods)


def _closest_name(key: str, names, cutoff: float = 0.72) -> str | None:
    best, best_ratio = None, cutoff
    for n in names:
        ratio = SequenceMatcher(None, key, n).ratio()
        if ratio > best_ratio:
            best, best_ratio = n, ratio
    return best


def build_geo_index(points, aliases: dict = NEIGHBORHOOD_ZIPS) -> GeoIndex:
    """Build a GeoIndex from (zip, lat, lon) triples. A ZIP centroid is the mean
    coordinate of that ZIP's points; a neighborhood resolves to the (restaurant-
    count-weighted) centroid of its present ZIPs. Triples with no ZIP or no
    coordinate are skipped."""
    acc = defaultdict(lambda: [0.0, 0.0, 0])   # zip -> [sum_lat, sum_lon, n]
    for z, lat, lon in points:
        if not z or lat is None or lon is None:
            continue
        a = acc[z]
        a[0] += lat
        a[1] += lon
        a[2] += 1
    zip_centroids = {z: (a[0] / a[2], a[1] / a[2]) for z, a in acc.items() if a[2]}

    neighborhoods = {}
    for name, zips in aliases.items():
        present = [z for z in zips if z in acc]
        if not present:
            continue
        n = sum(acc[z][2] for z in present)
        lat = sum(acc[z][0] for z in present) / n
        lon = sum(acc[z][1] for z in present) / n
        neighborhoods[name] = (lat, lon)
    return GeoIndex(zip_centroids, neighborhoods)


def geo_index_from_seed(seed: list) -> GeoIndex:
    """Build the index from prototype seed dicts (ZIP parsed off the address)."""
    def triple(r):
        loc = (r.get("location") or {}).get("coordinates")
        if not loc:
            return (None, None, None)
        lon, lat = loc
        return (zip_of(r.get("address")), lat, lon)
    return build_geo_index(triple(r) for r in seed)


# --------------------------------------------------------------------------
# Taste profile (stands in for the taste_profiles row in the real schema)
# --------------------------------------------------------------------------
@dataclass
class TasteProfile:
    cuisines_preferred: dict[str, float] = field(default_factory=dict)  # weighted
    price_pref: list[int] = field(default_factory=lambda: [1, 2, 3])
    dietary_restrictions: list[str] = field(default_factory=list)
    ambiance_prefs: list[str] = field(default_factory=list)
    summary: str = ""

    def compact(self) -> dict[str, Any]:
        return {
            "cuisines_preferred": self.cuisines_preferred,
            "price_pref": self.price_pref,
            "dietary_restrictions": self.dietary_restrictions,
            "ambiance_prefs": self.ambiance_prefs,
            "summary": self.summary,
        }


@dataclass
class Constraints:
    party_size: int = 2
    when: datetime | None = None        # used for open-hours filtering
    near: tuple[float, float] | None = None
    radius_km: float = DEFAULT_RADIUS_KM
    price_max: int | None = None
    cuisine_keywords: list[str] = field(default_factory=list)
    open_now: bool = False


# --------------------------------------------------------------------------
# Stage 1 — Retrieval & candidate pre-filtering
# --------------------------------------------------------------------------
def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    (lat1, lon1), (lat2, lon2) = a, b
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def latlon(r: dict) -> tuple[float, float]:
    lon, lat = r["location"]["coordinates"]
    return (lat, lon)


def is_open_at(r: dict, when: datetime) -> bool:
    hours = (r.get("attributes") or {}).get("hours") or {}
    span = hours.get(when.strftime("%A"))
    if not span or "-" not in span:
        return True  # unknown hours -> don't exclude
    try:
        start, end = span.split("-")
        sh, sm = (int(x) for x in start.split(":"))
        eh, em = (int(x) for x in end.split(":"))
    except ValueError:
        return True
    start_min, end_min = sh * 60 + sm, eh * 60 + em
    now_min = when.hour * 60 + when.minute
    if end_min <= start_min:           # past-midnight close
        return now_min >= start_min or now_min <= end_min
    return start_min <= now_min <= end_min


def matches_cuisine(r: dict, keywords: list[str]) -> bool:
    if not keywords:
        return True
    cats = " ".join(r.get("categories") or []).lower()
    return any(k.lower() in cats for k in keywords)


def retrieve(seed: list[dict], c: Constraints, cap: int = CANDIDATE_CAP) -> list[dict]:
    """Apply hard constraints, then trim to the top `cap` by rating quality."""
    out = []
    for r in seed:
        if c.price_max is not None and (r.get("price_level") or 99) > c.price_max:
            continue
        if not matches_cuisine(r, c.cuisine_keywords):
            continue
        if c.near is not None:
            if haversine_km(c.near, latlon(r)) > c.radius_km:
                continue
        if c.open_now and c.when is not None and not is_open_at(r, c.when):
            continue
        out.append(r)

    # Pre-rank cheaply (stand-in for pgvector): rating, then volume.
    out.sort(key=lambda r: (r.get("rating") or 0, r.get("rating_count") or 0), reverse=True)
    return out[:cap]


def compact_candidate(r: dict, c: Constraints) -> dict[str, Any]:
    """Only fields that affect ranking — keeps token cost low (design doc 4.1)."""
    feats = (r.get("attributes") or {}).get("features") or {}
    rec = {
        "id": r["id"],
        "name": r["name"],
        "categories": r.get("categories"),
        "price_level": r.get("price_level"),
        "rating": r.get("rating"),
        "rating_count": r.get("rating_count"),
        "outdoor_seating": feats.get("OutdoorSeating"),
        "alcohol": feats.get("Alcohol"),
        "takeout": feats.get("RestaurantsTakeOut"),
        "address": r.get("address"),
    }
    if c.near is not None:
        rec["distance_km"] = round(haversine_km(c.near, latlon(r)), 2)
    return rec


# --------------------------------------------------------------------------
# Stage 2 — Prompt assembly + LLM ranking
# --------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are a restaurant recommender. Rank ONLY the candidates provided. "
    "Never invent restaurants or facts not present in the candidate data. "
    "Use the diner profile and constraints to decide fit, and write a short, "
    "specific reason that references why each pick fits THIS diner. "
    "Return ONLY valid JSON matching the schema. No prose, no markdown."
)

SCHEMA_HINT = """Return JSON exactly in this shape:
{
  "picks": [
    { "restaurant_id": "<id from candidates>", "match_score": 0-100,
      "reasons": ["short reason", "short reason"] }
  ]
}
Rank best-first. Include 3-6 picks. restaurant_id MUST be one of the candidate ids."""


def assemble_messages(query: str, profile: TasteProfile, candidates: list[dict],
                      c: Constraints) -> list[dict]:
    when = c.when.strftime("%A %H:%M") if c.when else "unspecified"
    user = (
        f'Request: "{query}"\n\n'
        f"Diner profile: {json.dumps(profile.compact())}\n\n"
        f"Constraints: party_size={c.party_size}, when={when}, "
        f"price_max={c.price_max}, radius_km={c.radius_km}\n\n"
        f"Candidates ({len(candidates)}): {json.dumps(candidates)}\n\n"
        f"{SCHEMA_HINT}"
    )
    return [{"role": "user", "content": user}]


# --------------------------------------------------------------------------
# Local fake LLM — deterministic, offline test affordance (no key, no network).
# Enable with FAKE_LLM=1. Lets the llm / llm-repair / render paths and the taste
# summary run in tests and demos without the real API. Inert unless the env var
# is set, so it never affects production.
# --------------------------------------------------------------------------
# FAKE_LLM values that select a specific variant (any other truthy value = a
# normal valid ranking): 'hallucinate' adds a bogus id the guard must drop;
# 'malformed' returns bad JSON on the first call to exercise the repair retry.
_FAKE_HALLUCINATED_ID = "HALLUCINATED-NOT-A-CANDIDATE"


def _fake_mode() -> str:
    return os.getenv("FAKE_LLM", "").strip().lower()


def _fake_llm_enabled() -> bool:
    return _fake_mode() not in ("", "0", "false", "no")


def _is_repair_call(messages: list[dict]) -> bool:
    # rank()'s repair retry prepends an assistant prefill; the first call has none.
    return any(m.get("role") == "assistant" for m in messages)


def _extract_candidate_ids(messages: list[dict]) -> list[str]:
    text = " ".join(
        m.get("content", "") for m in messages if isinstance(m.get("content"), str)
    )
    return re.findall(r'"id":\s*"([^"]+)"', text)


def _fake_ranking_json(messages: list[dict]) -> str:
    """Canned ranking over the real candidate ids. FAKE_LLM picks the variant:
    valid (default), 'hallucinate' (adds a bogus id), or 'malformed' (bad JSON on
    the first call, valid on the repair retry)."""
    mode = _fake_mode()
    if mode == "malformed" and not _is_repair_call(messages):
        return "{not valid json at all"          # -> parse error -> repair retry

    ids = _extract_candidate_ids(messages)
    picks = [
        {
            "restaurant_id": rid,
            "match_score": max(50, 96 - i * 7),
            "reasons": [
                "fake-llm: matches your stated preferences",
                "fake-llm: fits the requested vibe and price",
            ],
        }
        for i, rid in enumerate(ids[:5])
    ]
    if mode == "hallucinate":
        picks.insert(
            0,
            {
                "restaurant_id": _FAKE_HALLUCINATED_ID,
                "match_score": 99,
                "reasons": ["fake-llm: this id is not in the candidate set"],
            },
        )
    return json.dumps({"picks": picks})


def _fake_taste_summary(profile: dict) -> str:
    cuisines = profile.get("cuisines_preferred") or {}
    top = sorted(cuisines, key=cuisines.get, reverse=True)[:3]
    prices = profile.get("price_pref") or []
    bits = []
    if top:
        bits.append("you gravitate toward " + ", ".join(top))
    if prices:
        bits.append("comfortable around " + "/".join("$" * p for p in sorted(prices)))
    return "fake-llm: " + ("; ".join(bits) if bits else "you're open to most things") + "."


def call_llm(messages: list[dict]) -> str:
    if _fake_llm_enabled():
        return _fake_ranking_json(messages)
    import anthropic  # imported lazily so retrieval works without the SDK
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        temperature=0,                  # low temp for ranking consistency
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    return resp.content[0].text


# --------------------------------------------------------------------------
# Taste-profile summarization (TDD §3.1: the LLM also summarizes taste profiles)
# --------------------------------------------------------------------------
TASTE_SUMMARY_SYSTEM = (
    "You write a one-sentence, second-person taste summary for a diner, used to "
    "personalize restaurant recommendations. Be specific and natural; reference "
    "their cuisines, price comfort, dietary needs, and preferred ambiance when "
    "present. No preamble, no markdown, max ~30 words. Output only the sentence."
)


def summarize_taste_profile(profile: dict) -> str | None:
    """LLM one-liner from a compact taste profile dict. Returns None when no API
    key is set or the call fails, so callers can fall back to a templated summary.
    """
    if _fake_llm_enabled():
        return _fake_taste_summary(profile)
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic  # lazy import, same as ranking
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=120,
            temperature=0.4,            # a little warmth reads more natural here
            system=TASTE_SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(profile)}],
        )
        text = resp.content[0].text.strip()
        return text or None
    except Exception as e:                                   # never break the write path
        print(f"[warn] taste summary LLM failed ({e}); using template.", file=sys.stderr)
        return None


# --------------------------------------------------------------------------
# Stage 3 — Validate, hallucination-guard, hydrate, render
# --------------------------------------------------------------------------
def parse_picks(raw: str, valid_ids: set[str]) -> list[dict]:
    """Strict-ish JSON parse + hallucination guard. Raises on unrecoverable."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    data = json.loads(text)
    picks = data["picks"]
    clean = []
    for p in picks:
        rid = p.get("restaurant_id")
        if rid not in valid_ids:        # drop hallucinated ids
            continue
        score = p.get("match_score")
        reasons = p.get("reasons") or []
        if not isinstance(reasons, list):
            reasons = [str(reasons)]
        clean.append({"restaurant_id": rid, "match_score": score, "reasons": reasons})
    if not clean:
        raise ValueError("no valid picks after hallucination guard")
    return clean


def rank(query: str, profile: TasteProfile, candidates: list[dict],
         c: Constraints) -> tuple[list[dict], str]:
    """Returns (picks, mode). mode is 'llm', 'llm-repair', or 'fallback'."""
    valid_ids = {r["id"] for r in candidates}
    if not os.getenv("ANTHROPIC_API_KEY") and not _fake_llm_enabled():
        return _fallback(candidates), "fallback (no API key)"

    messages = assemble_messages(query, profile, candidates, c)
    try:
        return parse_picks(call_llm(messages), valid_ids), "llm"
    except Exception as e:                                  # one repair retry
        try:
            repair = messages + [
                {"role": "assistant", "content": "{"},
                {"role": "user",
                 "content": f"Your last output was invalid ({e}). "
                            f"Reply with ONLY the JSON object, nothing else."},
            ]
            return parse_picks(call_llm(repair), valid_ids), "llm-repair"
        except Exception as e2:
            print(f"[warn] LLM ranking failed ({e2}); using fallback.", file=sys.stderr)
            return _fallback(candidates), "fallback (llm error)"


def _fallback(candidates: list[dict]) -> list[dict]:
    """Design doc 4.1.2: graceful fallback to pre-ranking order."""
    return [
        {"restaurant_id": r["id"],
         "match_score": None,
         "reasons": [f'{r.get("rating")}★ from {r.get("rating_count")} reviews']}
        for r in candidates[:6]
    ]


def render(picks: list[dict], by_id: dict[str, dict], mode: str) -> None:
    print(f"\n{'='*64}\n  Recommendations  (ranking: {mode})\n{'='*64}")
    for i, p in enumerate(picks, 1):
        r = by_id[p["restaurant_id"]]
        score = p["match_score"]
        score_s = f"{score}/100" if score is not None else "—"
        price = "$" * (r.get("price_level") or 1)
        print(f"\n{i}. {r['name']}   [{score_s}]")
        print(f"   {price} · {', '.join((r.get('categories') or [])[:4])}")
        print(f"   {r.get('rating')}★ ({r.get('rating_count')})  ·  {r.get('address')}")
        for reason in p["reasons"]:
            print(f"   → {reason}")
    print()


# --------------------------------------------------------------------------
# Demo scenarios
# --------------------------------------------------------------------------
DEMOS = {
    "date_night": dict(
        query="cozy, romantic spot for a date — not too loud, wine, around $$$",
        profile=TasteProfile(
            cuisines_preferred={"Italian": 0.8, "French": 0.7, "Wine Bars": 0.6},
            price_pref=[2, 3], ambiance_prefs=["quiet", "intimate", "date-night"],
            summary="Loves intimate wine-forward dinners; dislikes loud, busy rooms.",
        ),
        constraints=Constraints(party_size=2, near=LANDMARKS["rittenhouse"],
                                radius_km=2.5, price_max=3),
    ),
    "cheap_eats": dict(
        query="cheap, fast, delicious lunch near Chinatown — solo, casual",
        profile=TasteProfile(
            cuisines_preferred={"Chinese": 0.9, "Vietnamese": 0.8, "Noodles": 0.7},
            price_pref=[1, 2], ambiance_prefs=["casual", "quick"],
            summary="Adventurous, budget-conscious; favors bold Asian flavors.",
        ),
        constraints=Constraints(party_size=1, near=LANDMARKS["chinatown"],
                                radius_km=1.5, price_max=2),
    ),
    "group_dinner": dict(
        query="lively place for a group birthday dinner, shareable plates, drinks",
        profile=TasteProfile(
            cuisines_preferred={"American": 0.6, "Mexican": 0.7, "Tapas": 0.8},
            price_pref=[2, 3], ambiance_prefs=["lively", "shareable", "group"],
            summary="Group host; wants energy, shared plates, a full bar.",
        ),
        constraints=Constraints(party_size=8, near=LANDMARKS["fishtown"],
                                radius_km=3.0, price_max=3),
    ),
}


def load_seed() -> list[dict]:
    if not SEED_PATH.exists():
        sys.exit(f"Seed not found: {SEED_PATH}\nRun the YelpData pipeline first.")
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def main() -> None:
    # The result cards print ★ and · ; the Windows console defaults to cp1252,
    # which can't encode them. Force UTF-8 so this runs without PYTHONIOENCODING.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="Restaurant recommendation prototype")
    ap.add_argument("--demo", choices=DEMOS.keys(), help="run a built-in scenario")
    ap.add_argument("--query", help="free-text request")
    ap.add_argument("--near", help="a ZIP code or Philadelphia neighborhood name")
    ap.add_argument("--price-max", type=int, choices=[1, 2, 3, 4])
    ap.add_argument("--cuisine", nargs="*", default=[], help="cuisine keyword filters")
    ap.add_argument("--radius", type=float, default=DEFAULT_RADIUS_KM)
    args = ap.parse_args()

    seed = load_seed()
    print(f"Loaded {len(seed)} restaurants from seed.")

    if args.demo:
        d = DEMOS[args.demo]
        query, profile, c = d["query"], d["profile"], d["constraints"]
    elif args.query:
        query = args.query
        profile = TasteProfile(summary="(no taste profile supplied)")
        near = None
        if args.near:
            index = geo_index_from_seed(seed)
            near = index.resolve(args.near)
            if near is None:
                sys.exit(
                    f"Unknown location '{args.near}'. Use a ZIP code or a "
                    f"neighborhood: {', '.join(index.place_names)}"
                )
        c = Constraints(
            near=near,
            price_max=args.price_max,
            cuisine_keywords=args.cuisine,
            radius_km=args.radius,
        )
    else:
        sys.exit("Provide --demo <name> or --query \"...\"")

    candidates = retrieve(seed, c)
    print(f"Stage 1: {len(candidates)} candidates after hard filters (cap {CANDIDATE_CAP}).")
    if not candidates:
        sys.exit("No candidates matched. Loosen filters (radius / price / cuisine).")

    compact = [compact_candidate(r, c) for r in candidates]
    picks, mode = rank(query, profile, compact, c)
    render(picks, {r["id"]: r for r in candidates}, mode)


if __name__ == "__main__":
    main()
