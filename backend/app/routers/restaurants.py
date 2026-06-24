"""Restaurant lookup so clients can find IDs to add to lists. Reads the seeded
cache (TDD §4.2 retrieval is a separate concern — this is just browse/detail)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..deps import get_db

router = APIRouter(prefix="/restaurants", tags=["restaurants"])


@router.get("", response_model=list[schemas.RestaurantOut])
def search_restaurants(
    q: Optional[str] = None,
    cuisine: Optional[str] = None,
    price_max: Optional[int] = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(models.Restaurant)
    if q:
        stmt = stmt.where(models.Restaurant.name.ilike(f"%{q}%"))
    if price_max is not None:
        stmt = stmt.where(models.Restaurant.price_level <= price_max)
    # In SQLite, DESC sorts NULL ratings last, which is what we want.
    stmt = stmt.order_by(models.Restaurant.rating.desc())
    # Over-fetch when filtering categories in Python, then trim.
    rows = db.scalars(stmt.limit(limit * 4 if cuisine else limit)).all()
    if cuisine:
        rows = [
            r for r in rows if cuisine.lower() in " ".join(r.categories or []).lower()
        ]
    return rows[:limit]


@router.get("/{restaurant_id}", response_model=schemas.RestaurantOut)
def get_restaurant(restaurant_id: str, db: Session = Depends(get_db)):
    r = db.get(models.Restaurant, restaurant_id)
    if r is None:
        raise HTTPException(404, "Restaurant not found")
    return r
