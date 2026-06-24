"""Visit endpoints (TDD §6: POST /visits). Recording a visit also reconciles the
core lists: the restaurant leaves Want-to-Try and joins Visited (PRD §4.1)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas, services, taste
from ..deps import get_current_user, get_db

router = APIRouter(tags=["visits"])


@router.post("/visits", response_model=schemas.VisitOut, status_code=201)
def record_visit(
    payload: schemas.VisitCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if db.get(models.Restaurant, payload.restaurant_id) is None:
        raise HTTPException(404, "Restaurant not found")
    if payload.sentiment is not None and payload.sentiment not in models.SENTIMENTS:
        raise HTTPException(422, f"sentiment must be one of {models.SENTIMENTS}")

    visit = models.Visit(
        user_id=user.id,
        restaurant_id=payload.restaurant_id,
        sentiment=payload.sentiment,
        user_rating=payload.user_rating,
        notes=payload.notes,
        visited_at=payload.visited_at or models.utcnow(),
    )
    db.add(visit)
    _move_to_visited(db, user, payload.restaurant_id)
    db.commit()
    db.refresh(visit)
    taste.refresh(db, user)  # visits are the highest-signal taste input (PRD §4.2)
    return visit


@router.get("/visits", response_model=list[schemas.VisitOut])
def list_visits(
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    return db.scalars(
        select(models.Visit)
        .where(models.Visit.user_id == user.id)
        .order_by(models.Visit.visited_at.desc())
    ).all()


def _move_to_visited(db: Session, user: models.User, restaurant_id: str) -> None:
    services.ensure_core_lists(db, user)
    lists = {
        lst.type: lst
        for lst in db.scalars(
            select(models.SavedList).where(models.SavedList.user_id == user.id)
        )
    }
    want, visited = lists.get(models.WANT_TO_TRY), lists.get(models.VISITED)

    if want:
        stale = db.scalar(
            select(models.ListItem).where(
                models.ListItem.list_id == want.id,
                models.ListItem.restaurant_id == restaurant_id,
            )
        )
        if stale:
            db.delete(stale)

    if visited:
        already = db.scalar(
            select(models.ListItem).where(
                models.ListItem.list_id == visited.id,
                models.ListItem.restaurant_id == restaurant_id,
            )
        )
        if already is None:
            db.add(models.ListItem(list_id=visited.id, restaurant_id=restaurant_id))
