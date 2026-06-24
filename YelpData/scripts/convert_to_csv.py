#!/usr/bin/env python3
"""
Convert restaurants_Philadelphia_schema.ndjson -> restaurants_Philadelphia_schema.csv

The restaurants table has nested columns (location, categories, attributes, raw).
CSV is flat, so those are written as JSON-encoded strings in their cells -- which
is exactly what Postgres COPY ... WITH (FORMAT csv) expects for jsonb columns
(and ST_GeomFromGeoJSON can parse the location cell on load).

Standard library only.
"""

import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))      # .../YelpData/scripts
OUTPUT_DIR = os.path.join(os.path.dirname(HERE), "output")
SRC = os.path.join(OUTPUT_DIR, "restaurants_Philadelphia_schema.ndjson")
OUT = os.path.join(OUTPUT_DIR, "restaurants_Philadelphia_schema.csv")

COLUMNS = [
    "id", "source", "source_id", "name", "location", "address",
    "price_level", "categories", "attributes", "rating", "rating_count",
    "embedding", "raw", "cached_at", "expires_at",
]

# Columns whose value is a nested object/array -> serialize as a JSON string.
JSON_COLUMNS = {"location", "categories", "attributes", "raw"}


def cell(col, value):
    if value is None:
        return ""  # empty -> NULL in Postgres COPY
    if col in JSON_COLUMNS:
        return json.dumps(value, ensure_ascii=False)
    return value


def main():
    n = 0
    with open(SRC, "r", encoding="utf-8") as fin, \
         open(OUT, "w", encoding="utf-8", newline="") as fout:
        writer = csv.writer(fout, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(COLUMNS)  # header
        for line in fin:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            writer.writerow([cell(c, rec.get(c)) for c in COLUMNS])
            n += 1
    print(f"Wrote {n} rows -> {OUT}")


if __name__ == "__main__":
    main()
