"""Cross-cutting helpers: dev-user provisioning and core-list management."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models

# Auth is undecided (TDD open question). For local dev we identify the user via
# an X-User-Id header and fall back to this fixed dev user when none is given.
DEV_USER_ID = "00000000-0000-0000-0000-000000000001"

# Display names for the two auto-created core lists.
CORE_LIST_NAMES = {
    models.WANT_TO_TRY: "Want to Try",
    models.VISITED: "Visited",
}


def get_or_create_user(db: Session, user_id: str) -> models.User:
    user = db.get(models.User, user_id)
    if user is None:
        user = models.User(id=user_id, display_name="Dev User")
        db.add(user)
        db.flush()
        ensure_core_lists(db, user)
        db.commit()
    return user


def ensure_core_lists(db: Session, user: models.User) -> None:
    """Every user has exactly one want_to_try and one visited list (PRD §4.1)."""
    existing = {
        lst.type
        for lst in db.scalars(
            select(models.SavedList).where(models.SavedList.user_id == user.id)
        )
    }
    for list_type, name in CORE_LIST_NAMES.items():
        if list_type not in existing:
            db.add(models.SavedList(user_id=user.id, type=list_type, name=name))
    db.flush()
