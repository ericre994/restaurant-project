"""Authentication endpoints — local email/password accounts.

  POST /auth/signup   create an account            -> {token, user}
  POST /auth/login    email + password              -> {token, user}
  POST /auth/logout   invalidate the current token  -> 204

The token is an opaque bearer credential; send it as `Authorization: Bearer
<token>` on subsequent requests (see deps.get_current_user). Real production
auth (a managed provider) is still an open decision (TDD §9) — this is a
self-contained local implementation so each person's lists stay their own.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas, services
from ..deps import bearer_token, get_db

router = APIRouter(prefix="/auth", tags=["auth"])


def _valid_email(email: str) -> bool:
    email = email.strip()
    return "@" in email and "." in email.rsplit("@", 1)[-1]


@router.post("/signup", response_model=schemas.AuthOut, status_code=201)
def signup(payload: schemas.SignupRequest, db: Session = Depends(get_db)):
    if not _valid_email(payload.email):
        raise HTTPException(422, "enter a valid email address")
    try:
        user = services.create_account(
            db, payload.email, payload.password, payload.display_name
        )
    except services.EmailTaken:
        raise HTTPException(409, "an account with that email already exists")
    session = services.start_session(db, user)
    return schemas.AuthOut(token=session.token, user=schemas.UserOut.model_validate(user))


@router.post("/login", response_model=schemas.AuthOut)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = services.authenticate(db, payload.email, payload.password)
    if user is None:
        raise HTTPException(401, "invalid email or password")
    session = services.start_session(db, user)
    return schemas.AuthOut(token=session.token, user=schemas.UserOut.model_validate(user))


@router.post("/logout", status_code=204)
def logout(
    token: Optional[str] = Depends(bearer_token),
    db: Session = Depends(get_db),
):
    """Invalidate the presented session. Idempotent — no token is a no-op."""
    if token:
        services.end_session(db, token)
