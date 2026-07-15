"""Cross-cutting helpers: dev-user provisioning and core-list management."""
from datetime import timedelta
from typing import Dict, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models, security

# Sentinel for partial-update args: distinguishes "field omitted" (leave as-is)
# from "field set to None" (clear it). Callers pass UNSET for untouched fields.
UNSET = object()

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


# ---- Accounts + sessions (local email/password auth) ----------------------

SESSION_TTL = timedelta(days=30)  # long-lived so users "pick back up" next visit


class EmailTaken(Exception):
    """Signup with an email that already has an account."""


class UsernameTaken(Exception):
    """Signup with a username that's already claimed (case-insensitive)."""


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def create_account(
    db: Session,
    email: str,
    password: str,
    username: str,
    first_name: str,
    last_name: str,
) -> models.User:
    """Create a real account (hashed password) + its core lists. First/last name
    and a unique @username are required; the display name shown in the UI is the
    first name. Login stays by email. Raises EmailTaken / UsernameTaken on a
    collision (username uniqueness is case-insensitive)."""
    email = normalize_email(email)
    username = (username or "").strip()
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    if db.scalar(select(models.User).where(models.User.email == email)):
        raise EmailTaken(email)
    if db.scalar(
        select(models.User).where(func.lower(models.User.username) == username.lower())
    ):
        raise UsernameTaken(username)
    user = models.User(
        email=email,
        username=username,
        first_name=first_name,
        last_name=last_name,
        display_name=first_name,  # UI greets by first name
        password_hash=security.hash_password(password),
    )
    db.add(user)
    db.flush()
    ensure_core_lists(db, user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> Optional[models.User]:
    """Return the user for valid email+password, else None. A passwordless
    account (dev stub / X-User-Id bypass) never authenticates."""
    user = db.scalar(
        select(models.User).where(models.User.email == normalize_email(email))
    )
    if user is None or not user.password_hash:
        return None
    if not security.verify_password(password, user.password_hash):
        return None
    return user


def start_session(db: Session, user: models.User) -> models.AuthSession:
    session = models.AuthSession(
        token=security.new_token(),
        user_id=user.id,
        expires_at=models.utcnow() + SESSION_TTL,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def user_for_token(db: Session, token: str) -> Optional[models.User]:
    """Resolve a bearer token to its user, or None if unknown/expired."""
    session = db.get(models.AuthSession, token)
    if session is None:
        return None
    if session.expires_at and _aware(session.expires_at) < models.utcnow():
        return None
    return db.get(models.User, session.user_id)


def end_session(db: Session, token: str) -> None:
    session = db.get(models.AuthSession, token)
    if session is not None:
        db.delete(session)
        db.commit()


def _aware(dt):
    """SQLite hands datetimes back naive; treat them as UTC for comparison."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=models.timezone.utc)


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


# ---- Per-restaurant notes (shared across a user's lists) -------------------

def get_restaurant_note(
    db: Session, user: models.User, restaurant_id: str
) -> Optional[models.RestaurantNote]:
    return db.scalar(
        select(models.RestaurantNote).where(
            models.RestaurantNote.user_id == user.id,
            models.RestaurantNote.restaurant_id == restaurant_id,
        )
    )


def notes_map(
    db: Session, user: models.User, restaurant_ids: Iterable[str]
) -> Dict[str, models.RestaurantNote]:
    """{restaurant_id: RestaurantNote} for the given restaurants, for bulk
    hydration of list items without an N+1 query."""
    ids = list(restaurant_ids)
    if not ids:
        return {}
    rows = db.scalars(
        select(models.RestaurantNote).where(
            models.RestaurantNote.user_id == user.id,
            models.RestaurantNote.restaurant_id.in_(ids),
        )
    )
    return {n.restaurant_id: n for n in rows}


def upsert_restaurant_note(
    db: Session,
    user: models.User,
    restaurant_id: str,
    note=UNSET,
    tags=UNSET,
) -> models.RestaurantNote:
    """Create or update the user's note for a restaurant. Only the fields passed
    (i.e. not UNSET) are written, so a caller can touch tags without clearing the
    note. The row is flushed but not committed — the caller owns the transaction."""
    rec = get_restaurant_note(db, user, restaurant_id)
    if rec is None:
        rec = models.RestaurantNote(user_id=user.id, restaurant_id=restaurant_id, tags=[])
        db.add(rec)
    if note is not UNSET:
        rec.note = note
    if tags is not UNSET:
        rec.tags = tags or []
    rec.updated_at = models.utcnow()
    db.flush()
    return rec
