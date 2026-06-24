#!/usr/bin/env python3
"""
Extract the Yelp dataset tar and prepare restaurant rows for the `restaurants`
table defined in the Technical Design Doc.

Runs locally (no sandbox needed). Standard library only.

Usage:
    # 1) Just extract the tar:
    python extract_and_prepare_yelp.py --extract

    # 2) See which cities/states are actually in the data (Yelp has NO NYC data):
    python extract_and_prepare_yelp.py --summary

    # 3) Build seed files for restaurants in a chosen city:
    python extract_and_prepare_yelp.py --city "Philadelphia" --limit 1000

    # Do all of it at once:
    python extract_and_prepare_yelp.py --extract --summary --city "Philadelphia" --limit 1000
"""

import argparse
import json
import os
import tarfile
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))      # .../YelpData/scripts
ROOT = os.path.dirname(HERE)                            # .../YelpData
SOURCE_DIR = os.path.join(ROOT, "source")
OUTPUT_DIR = os.path.join(ROOT, "output")
TAR_PATH = os.path.join(SOURCE_DIR, "yelp_dataset.tar")
BUSINESS_FILE = os.path.join(SOURCE_DIR, "yelp_academic_dataset_business.json")


def extract():
    """Extract the tar into this folder (only members not already present)."""
    if not os.path.exists(TAR_PATH):
        raise SystemExit(f"Tar not found: {TAR_PATH}")
    print(f"Extracting {TAR_PATH} ...")
    os.makedirs(SOURCE_DIR, exist_ok=True)
    with tarfile.open(TAR_PATH, "r:*") as tar:
        tar.extractall(SOURCE_DIR)
    print("Done. Files now in:", SOURCE_DIR)


def iter_businesses():
    """Yield one business dict per line from the (large) business json file."""
    if not os.path.exists(BUSINESS_FILE):
        raise SystemExit(
            f"{BUSINESS_FILE} not found. Run with --extract first."
        )
    with open(BUSINESS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def is_restaurant(biz):
    cats = biz.get("categories") or ""
    return "restaurant" in cats.lower()


def summary():
    """Print restaurant counts by state and by city so you can pick a target."""
    by_state, by_city = Counter(), Counter()
    total = 0
    for biz in iter_businesses():
        if is_restaurant(biz):
            total += 1
            by_state[biz.get("state", "?")] += 1
            by_city[f"{biz.get('city','?')}, {biz.get('state','?')}"] += 1
    print(f"\nTotal restaurants in dataset: {total}\n")
    print("Top states:")
    for s, n in by_state.most_common(15):
        print(f"  {s:<4} {n}")
    print("\nTop cities:")
    for c, n in by_city.most_common(20):
        print(f"  {c:<28} {n}")
    print("\n(Note: the Yelp Open Dataset contains NO New York City data.)")


# --- mapping to the `restaurants` schema from the Technical Design Doc -------

def to_restaurant_row(biz):
    """Map a Yelp business object onto the restaurants table columns."""
    attrs = biz.get("attributes") or {}
    # Yelp encodes price as RestaurantsPriceRange2: "1".."4"
    price_level = None
    raw_price = attrs.get("RestaurantsPriceRange2")
    if raw_price not in (None, "None"):
        try:
            price_level = int(raw_price)
        except (ValueError, TypeError):
            price_level = None

    categories = [c.strip() for c in (biz.get("categories") or "").split(",") if c.strip()]
    address = ", ".join(
        p for p in [biz.get("address"), biz.get("city"),
                    biz.get("state"), biz.get("postal_code")] if p
    )
    now = datetime.now(timezone.utc)

    return {
        "id": str(uuid.uuid4()),
        "source": "yelp",
        "source_id": biz.get("business_id"),
        "name": biz.get("name"),
        "latitude": biz.get("latitude"),     # -> location geography(Point)
        "longitude": biz.get("longitude"),
        "address": address,
        "price_level": price_level,
        "categories": categories,            # -> jsonb
        "attributes": {                      # -> jsonb (attributes + hours)
            "attributes": attrs,
            "hours": biz.get("hours"),
        },
        "rating": biz.get("stars"),
        "rating_count": biz.get("review_count"),
        "embedding": None,                   # filled later once model/dim chosen
        "raw": biz,                          # -> jsonb, full provider payload
        "cached_at": now.isoformat(),
        "expires_at": (now + timedelta(days=30)).isoformat(),
    }


def sql_literal(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (dict, list)):
        return "'" + json.dumps(v).replace("'", "''") + "'"
    return "'" + str(v).replace("'", "''") + "'"


def build(city, state, limit):
    rows = []
    for biz in iter_businesses():
        if not is_restaurant(biz):
            continue
        if city and (biz.get("city") or "").lower() != city.lower():
            continue
        if state and (biz.get("state") or "").upper() != state.upper():
            continue
        rows.append(to_restaurant_row(biz))
        if limit and len(rows) >= limit:
            break

    target = city or state or "all"
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    json_out = os.path.join(OUTPUT_DIR, f"restaurants_seed_{target}.json".replace(" ", "_"))
    sql_out = os.path.join(OUTPUT_DIR, f"restaurants_seed_{target}.sql".replace(" ", "_"))

    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    with open(sql_out, "w", encoding="utf-8") as f:
        f.write("-- Seed for restaurants table. location built from lat/lng.\n")
        for r in rows:
            loc = ("NULL" if r["latitude"] is None or r["longitude"] is None
                   else f"ST_SetSRID(ST_MakePoint({r['longitude']},{r['latitude']}),4326)::geography")
            f.write(
                "INSERT INTO restaurants "
                "(id, source, source_id, name, location, address, price_level, "
                "categories, attributes, rating, rating_count, embedding, raw, "
                "cached_at, expires_at) VALUES ("
                f"{sql_literal(r['id'])}, {sql_literal(r['source'])}, "
                f"{sql_literal(r['source_id'])}, {sql_literal(r['name'])}, "
                f"{loc}, {sql_literal(r['address'])}, {sql_literal(r['price_level'])}, "
                f"{sql_literal(r['categories'])}, {sql_literal(r['attributes'])}, "
                f"{sql_literal(r['rating'])}, {sql_literal(r['rating_count'])}, "
                f"NULL, {sql_literal(r['raw'])}, "
                f"{sql_literal(r['cached_at'])}, {sql_literal(r['expires_at'])});\n"
            )

    print(f"Wrote {len(rows)} rows ->")
    print(f"  {json_out}")
    print(f"  {sql_out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", action="store_true", help="extract the tar")
    ap.add_argument("--summary", action="store_true", help="print city/state counts")
    ap.add_argument("--city", help="filter to this city (e.g. Philadelphia)")
    ap.add_argument("--state", help="filter to this 2-letter state code")
    ap.add_argument("--limit", type=int, default=1000, help="max rows (0 = no cap)")
    args = ap.parse_args()

    if args.extract:
        extract()
    if args.summary:
        summary()
    if args.city or args.state:
        build(args.city, args.state, args.limit or None)
    if not (args.extract or args.summary or args.city or args.state):
        # Default (e.g. when run via the editor's Run button, no CLI args):
        # parse ALL Philadelphia restaurants.
        build("Philadelphia", None, None)


if __name__ == "__main__":
    main()
