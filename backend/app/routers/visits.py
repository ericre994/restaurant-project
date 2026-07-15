"""Visit endpoints (TDD §6: POST /visits). Recording a visit also reconciles the
core lists: the restaurant leaves Want-to-Try and joins Visited (PRD §4.1)."""
from datetime import timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas, services, taste
from ..deps import get_current_user, get_db

router = APIRouter(tags=["visits"])


def _is_future_date(visited_at) -> bool:
    """True if `visited_at` falls on a calendar day after today (UTC). Compares
    dates, not instants, so logging a visit for earlier today is always allowed
    even if the client sent a noon timestamp that is technically ahead of `now`."""
    vt = visited_at if visited_at.tzinfo else visited_at.replace(tzinfo=timezone.utc)
    return vt.astimezone(timezone.utc).date() > models.utcnow().date()


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
    if payload.visited_at is not None and _is_future_date(payload.visited_at):
        raise HTTPException(422, "visited_at cannot be in the future")

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


def _owned_visit(db: Session, user: models.User, visit_id: str) -> models.Visit:
    visit = db.get(models.Visit, visit_id)
    if visit is None or visit.user_id != user.id:
        raise HTTPException(404, "Visit not found")
    return visit


@router.patch("/visits/{visit_id}", response_model=schemas.VisitOut)
def update_visit(
    visit_id: str,
    payload: schemas.VisitUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Edit a logged visit (sentiment / rating / notes / date). Owner-only.
    Same validation as creating one; list membership is unaffected."""
    visit = _owned_visit(db, user, visit_id)
    fields = payload.model_dump(exclude_unset=True)
    if "sentiment" in fields and fields["sentiment"] is not None and fields["sentiment"] not in models.SENTIMENTS:
        raise HTTPException(422, f"sentiment must be one of {models.SENTIMENTS}")
    if fields.get("visited_at") is not None and _is_future_date(fields["visited_at"]):
        raise HTTPException(422, "visited_at cannot be in the future")
    for key, value in fields.items():
        setattr(visit, key, value)
    db.commit()
    db.refresh(visit)
    taste.refresh(db, user)  # edited sentiment/rating feeds the taste profile
    return visit


@router.delete("/visits/{visit_id}", status_code=204)
def delete_visit(
    visit_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Delete a logged visit. Owner-only. Leaves list membership untouched — the
    restaurant stays on Visited unless removed there explicitly."""
    visit = _owned_visit(db, user, visit_id)
    db.delete(visit)
    db.commit()
    taste.refresh(db, user)


@router.get("/visits", response_model=list[schemas.VisitOut])
def list_visits(
    restaurant_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Visit history, newest first. Pass `restaurant_id` to get just one
    restaurant's visits (each logged visit is a separate row — the UI logs one
    per outing)."""
    stmt = select(models.Visit).where(models.Visit.user_id == user.id)
    if restaurant_id is not None:
        stmt = stmt.where(models.Visit.restaurant_id == restaurant_id)
    return db.scalars(stmt.order_by(models.Visit.visited_at.desc())).all()


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
