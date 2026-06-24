# YelpData

Yelp Open Dataset and the pipeline that turns it into `restaurants`-table seed data.

> The Yelp Open Dataset is **academic-use only** — fine for local dev/testing, not
> for commercial or production use. See `docs/`.

## Folder layout

```
YelpData/
  source/    Raw Yelp dataset (yelp_dataset.tar + yelp_academic_dataset_*.json)
  docs/      Yelp dataset documentation & terms of use (PDFs)
  scripts/   Pipeline scripts (.py) and their double-click runners (.bat)
  output/    Generated restaurants-table data (seed + schema-clean + csv)
  logs/      Run logs from the .bat runners
  README.md
```

## Pipeline (run from `scripts/`, in order)

1. `run_philadelphia.bat` -> `extract_and_prepare_yelp.py`
   Filters the Yelp data to Philadelphia restaurants and maps them onto the
   `restaurants` schema. Produces `output/restaurants_seed_Philadelphia.{json,sql}`.
2. `run_normalize.bat` -> `normalize_to_schema.py`
   Cleans the seed into strictly schema-conformant records (GeoJSON `location`,
   parsed `attributes`, schema columns only).
   Produces `output/restaurants_Philadelphia_schema.{json,ndjson}`.
3. `run_csv.bat` -> `convert_to_csv.py`
   Flattens the schema records to CSV (nested columns as JSON strings).
   Produces `output/restaurants_Philadelphia_schema.csv`.

Each `.bat` writes its console output to `logs/`.
