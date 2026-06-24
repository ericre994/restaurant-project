"""Current-user + taste-profile endpoints (TDD §6: GET /me, GET/PUT /me/taste-profile)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas, taste
from ..deps import get_current_user, get_db

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=schemas.UserOut)
def get_me(user: models.User = Depends(get_current_user)):
    return user


@router.get("/taste-profile", response_model=schemas.TasteProfileOut)
def get_taste_profile(
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    return taste.get_or_create(db, user)


@router.put("/taste-profile", response_model=schemas.TasteProfileOut)
def update_taste_profile(
    payload: schemas.TasteProfileUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    profile = taste.get_or_create(db, user)
    # Only overwrite fields the client actually sent (exclude_unset).
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    # Explicit prefs (dietary, ambiance) appear in the summary — refresh it.
    profile.derived_summary = taste.build_summary(profile)
    profile.updated_at = models.utcnow()
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile
