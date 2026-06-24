"""Load the Philadelphia seed into the restaurants table and create the dev user.

    python -m app.seed        (from the backend/ directory)

Idempotent: skips the restaurant load if the table already has rows.
"""
import json
from pathlib import Path

from sqlalchemy import func, select

from . import models, services
from .db import SessionLocal, engine

SEED_PATH = (
    Path(__file__).resolve().parents[2]
    / "YelpData" / "output" / "restaurants_Philadelphia_schema.json"
)


def _to_restaurant(r: dict) -> models.Restaurant:
    """Build a Restaurant row, deriving the indexable geo/cuisine columns."""
    coords = (r.get("location") or {}).get("coordinates") or [None, None]
    lon, lat = coords[0], coords[1]
    categories = r.get("categories") or []
    categories_text = ", ".join(categories).lower() if categories else None
    return models.Restaurant(
        id=r["id"],
        source=r.get("source"),
        source_id=r.get("source_id"),
        name=r.get("name"),
        location=r.get("location"),
        address=r.get("address"),
        price_level=r.get("price_level"),
        categories=categories,
        attributes=r.get("attributes"),
        rating=r.get("rating"),
        rating_count=r.get("rating_count"),
        latitude=lat,
        longitude=lon,
        categories_text=categories_text,
    )


def run() -> None:
    models.Base.metadata.create_all(bind=engine)
    if not SEED_PATH.exists():
        raise SystemExit(f"Seed not found: {SEED_PATH}\nRun the YelpData pipeline first.")

    rows = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    db = SessionLocal()
    try:
        existing = db.scalar(select(func.count()).select_from(models.Restaurant))
        if existing:
            print(f"restaurants table already has {existing} rows; skipping load.")
        else:
            db.bulk_save_objects([_to_restaurant(r) for r in rows])
            db.commit()
            print(f"Loaded {len(rows)} restaurants.")

        services.get_or_create_user(db, services.DEV_USER_ID)
        print(f"Dev user ready: {services.DEV_USER_ID}")
    finally:
        db.close()


if __name__ == "__main__":
    run()
