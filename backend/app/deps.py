"""FastAPI dependencies: DB session + current-user resolution.

Auth precedence:
  1. `Authorization: Bearer <token>`  -> the real account owning that session.
  2. `X-User-Id: <id>`  -> DEV-ONLY stub: any id gets its own isolated data.
     Kept so the dev harness and the existing test suite keep working; this
     bypass should be gated behind a dev flag (or removed) before production.
  3. neither  -> the fixed dev user.
"""
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from . import models, services
from .db import SessionLocal


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def bearer_token(authorization: Optional[str] = Header(default=None)) -> Optional[str]:
    """The token from an `Authorization: Bearer <token>` header, if present."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def get_current_user(
    db: Session = Depends(get_db),
    token: Optional[str] = Depends(bearer_token),
    x_user_id: Optional[str] = Header(default=None),
) -> models.User:
    if token:
        user = services.user_for_token(db, token)
        if user is None:
            raise HTTPException(401, "invalid or expired session")
        return user
    # Dev stub (no real auth): identify by X-User-Id, default to the dev user.
    return services.get_or_create_user(db, x_user_id or services.DEV_USER_ID)
