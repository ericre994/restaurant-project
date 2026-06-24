"""Recommendation endpoints (TDD §6).

  POST /recommendations               run the pipeline; writes a recommendation_logs row
  POST /recommendations/{id}/feedback record per-item feedback (TDD §4.5 loop)
  GET  /recommendations/{id}          inspect a logged recommendation

Thin HTTP layer over `app.recommender`, which runs the prototype pipeline
against the DB. Works with or without an ANTHROPIC_API_KEY — without one, it
returns the rating-sorted fallback (PRD §4.2 reliability requirement).

Neighborhood landmarks accepted by `near` (from the prototype): chinatown,
center city, rittenhouse, fishtown, south philly, university city, old city.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, recommender, schemas, taste
from ..deps import get_current_user, get_db

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.post("", response_model=schemas.RecommendationResponse)
def create_recommendations(
    payload: schemas.RecommendationRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    started = time.perf_counter()
    try:
        result = recommender.recommend(
            db,
            user,
            query=payload.query,
            near=payload.near,
            lat=payload.lat,
            lng=payload.lng,
            radius_km=payload.radius_km,
            price_max=payload.price_max,
            cuisine=payload.cuisine,
            open_now=payload.open_now,
            party_size=payload.party_size,
        )
    except ValueError as exc:  # e.g. unknown landmark
        raise HTTPException(422, str(exc))

    latency_ms = int((time.perf_counter() - started) * 1000)
    log = recommender.persist_log(db, user, payload, result, latency_ms)

    out_picks = [
        schemas.RecommendationPick(
            restaurant_id=p["restaurant_id"],
            match_score=p.get("match_score"),
            reasons=p.get("reasons") or [],
            restaurant=schemas.RestaurantOut.model_validate(result.by_id[p["restaurant_id"]]),
        )
        for p in result.picks
        if p["restaurant_id"] in result.by_id  # hallucination guard already ran; belt + braces
    ]
    return schemas.RecommendationResponse(
        recommendation_id=log.id,
        query=payload.query,
        mode=result.mode,
        candidate_count=result.candidate_count,
        picks=out_picks,
    )


def _owned_log(db: Session, user: models.User, rec_id: str) -> models.RecommendationLog:
    log = db.get(models.RecommendationLog, rec_id)
    if log is None or log.user_id != user.id:
        raise HTTPException(404, "Recommendation not found")
    return log


@router.post("/{rec_id}/feedback", response_model=schemas.RecommendationLogOut)
def record_feedback(
    rec_id: str,
    payload: schemas.FeedbackCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    log = _owned_log(db, user, rec_id)
    if payload.action not in models.FEEDBACK_ACTIONS:
        raise HTTPException(422, f"action must be one of {models.FEEDBACK_ACTIONS}")
    if payload.restaurant_id not in (log.shown_restaurant_ids or []):
        raise HTTPException(422, "restaurant was not shown in this recommendation")

    # Reassign a new dict so SQLAlchemy sees the JSON column as dirty (in-place
    # mutation of a JSON column isn't tracked by default).
    feedback = dict(log.user_feedback or {})
    events = list(feedback.get(payload.restaurant_id, []))
    events.append({"action": payload.action, "at": models.utcnow().isoformat()})
    feedback[payload.restaurant_id] = events
    log.user_feedback = feedback

    db.add(log)
    db.commit()
    db.refresh(log)
    taste.refresh(db, user)  # feedback feeds the taste profile (TDD §4.5)
    return log


@router.get("/{rec_id}", response_model=schemas.RecommendationLogOut)
def get_recommendation(
    rec_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return _owned_log(db, user, rec_id)
