#!/usr/bin/env python3
"""
Normalize restaurants_seed_Philadelphia.json into records that conform exactly
to the `restaurants` table schema (Technical Design Doc section 5.1).

What it cleans up vs. the raw seed:
  - location: emitted as GeoJSON Point {"type":"Point","coordinates":[lng,lat]}
    (the natural representation for a geography(Point) column) instead of two
    loose latitude/longitude fields.
  - attributes: Yelp stores nested values as Python-literal STRINGS
    (e.g. "True", "u'free'", "{'garage': False}"). These are parsed into real
    JSON booleans / nulls / strings / nested objects, and grouped under
    {"features": {...}, "hours": {...}} to match the schema note
    ("attributes jsonb: hours, features, etc.").
  - only schema columns are kept: id, source, source_id, name, location,
    address, price_level, categories, attributes, rating, rating_count,
    embedding, raw, cached_at, expires_at.

Outputs:
  - restaurants_Philadelphia_schema.json   (pretty array)
  - restaurants_Philadelphia_schema.ndjson (one record per line, for bulk load)

Standard library only. Run via the .bat or `python normalize_to_schema.py`.
"""

import ast
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))      # .../YelpData/scripts
OUTPUT_DIR = os.path.join(os.path.dirname(HERE), "output")
SRC = os.path.join(OUTPUT_DIR, "restaurants_seed_Philadelphia.json")
OUT_JSON = os.path.join(OUTPUT_DIR, "restaurants_Philadelphia_schema.json")
OUT_NDJSON = os.path.join(OUTPUT_DIR, "restaurants_Philadelphia_schema.ndjson")

SCHEMA_COLUMNS = [
    "id", "source", "source_id", "name", "location", "address",
    "price_level", "categories", "attributes", "rating", "rating_count",
    "embedding", "raw", "cached_at", "expires_at",
]


def parse_value(v):
    """Turn a Yelp attribute value into a real JSON-able Python value."""
    if not isinstance(v, str):
        return v
    s = v.strip()
    # ast.literal_eval understands True/False/None, ints, u'...' strings,
    # and nested dicts like "{'garage': False}". Fall back to the raw string.
    try:
        parsed = ast.literal_eval(s)
    except (ValueError, SyntaxError):
        return v
    # Recurse into dicts so inner string-encoded values are cleaned too.
    if isinstance(parsed, dict):
        return {k: parse_value(val) for k, val in parsed.items()}
    return parsed


def normalize_attributes(attr_block):
    """attr_block is {"attributes": {...}, "hours": {...}} from the seed."""
    raw_features = (attr_block or {}).get("attributes") or {}
    hours = (attr_block or {}).get("hours")
    features = {k: parse_value(v) for k, v in raw_features.items()}
    return {"features": features, "hours": hours}


def to_schema_record(rec):
    lat = rec.get("latitude")
    lng = rec.get("longitude")
    location = None
    if lat is not None and lng is not None:
        location = {"type": "Point", "coordinates": [lng, lat]}

    return {
        "id": rec.get("id"),
        "source": rec.get("source"),
        "source_id": rec.get("source_id"),
        "name": rec.get("name"),
        "location": location,
        "address": rec.get("address"),
        "price_level": rec.get("price_level"),
        "categories": rec.get("categories") or [],
        "attributes": normalize_attributes(rec.get("attributes")),
        "rating": rec.get("rating"),
        "rating_count": rec.get("rating_count"),
        "embedding": rec.get("embedding"),  # stays null
        "raw": rec.get("raw"),
        "cached_at": rec.get("cached_at"),
        "expires_at": rec.get("expires_at"),
    }


def main():
    with open(SRC, "r", encoding="utf-8") as f:
        rows = json.load(f)

    cleaned = [to_schema_record(r) for r in rows]

    # sanity: every record has exactly the schema columns
    for r in cleaned:
        assert list(r.keys()) == SCHEMA_COLUMNS, r.keys()

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)

    with open(OUT_NDJSON, "w", encoding="utf-8") as f:
        for r in cleaned:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # quick coverage stats
    n = len(cleaned)
    with_price = sum(1 for r in cleaned if r["price_level"] is not None)
    with_loc = sum(1 for r in cleaned if r["location"] is not None)
    with_rating = sum(1 for r in cleaned if r["rating"] is not None)
    print(f"Normalized {n} records.")
    print(f"  with location:    {with_loc}")
    print(f"  with price_level: {with_price}")
    print(f"  with rating:      {with_rating}")
    print(f"Wrote:\n  {OUT_JSON}\n  {OUT_NDJSON}")


if __name__ == "__main__":
    main()
