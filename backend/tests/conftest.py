"""Test fixtures: an isolated temp SQLite DB seeded with two restaurants.

DATABASE_URL must be set BEFORE app modules import (they build the engine at
import time), so it's set here at the top of the earliest-imported test module.
"""
import os
import tempfile
from pathlib import Path

_DB_FILE = Path(tempfile.gettempdir()) / "restaurant_lists_test.db"
if _DB_FILE.exists():
    _DB_FILE.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.as_posix()}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _seed_restaurants():
    models.Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    # Two Philadelphia-area points ~0.6 km apart, plus a far-away decoy.
    db.add(
        models.Restaurant(
            id="r1", source="yelp", source_id="s1", name="Pizza Place",
            categories=["Pizza", "Italian"], categories_text="pizza, italian",
            price_level=2, rating=4.5, rating_count=100,
            location={"type": "Point", "coordinates": [-75.1555, 39.9554]},
            latitude=39.9554, longitude=-75.1555,
        )
    )
    db.add(
        models.Restaurant(
            id="r2", source="yelp", source_id="s2", name="Sushi Spot",
            categories=["Sushi", "Japanese"], categories_text="sushi, japanese",
            price_level=3, rating=4.8, rating_count=50,
            location={"type": "Point", "coordinates": [-75.1500, 39.9560]},
            latitude=39.9560, longitude=-75.1500,
        )
    )
    db.add(
        models.Restaurant(
            id="r3", source="yelp", source_id="s3", name="Far Diner",
            categories=["Diner"], categories_text="diner",
            price_level=1, rating=5.0, rating_count=10,
            location={"type": "Point", "coordinates": [-80.0000, 40.4400]},
            latitude=40.4400, longitude=-80.0000,
        )
    )
    db.commit()
    db.close()


@pytest.fixture
def client():
    return TestClient(app)
