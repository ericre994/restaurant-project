"""FastAPI dependencies: DB session + (stub) current-user resolution."""
from typing import Optional

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from . import models, services
from .db import SessionLocal


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    db: Session = Depends(get_db),
    x_user_id: Optional[str] = Header(default=None),
) -> models.User:
    """Dev-only auth stub. Real auth (OAuth/managed provider) is a TDD open
    question; swap this dependency out when that's decided."""
    return services.get_or_create_user(db, x_user_id or services.DEV_USER_ID)
