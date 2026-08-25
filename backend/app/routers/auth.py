"""Registration, login, and the current-user endpoint."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import RateLimiter, get_current_user
from app.models import User
from app.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.security import (
    PasswordPolicyError,
    create_access_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Throttle credential stuffing. Keyed on the submitted email so one attacker
# cannot lock out every account by hammering a shared IP.
_login_limiter = RateLimiter(max_calls=8, window_seconds=60.0)

# A pre-computed hash used to keep the "unknown email" path as slow as the
# "wrong password" path, so response time does not reveal which accounts exist.
_DUMMY_HASH = hash_password("not-a-real-password-1")


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, session: Session = Depends(get_session)):
    email = payload.email.lower().strip()
    try:
        pw_hash = hash_password(payload.password)
    except PasswordPolicyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None

    user = User(email=email, password_hash=pw_hash)
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An account with that email already exists."
        ) from None

    token, expires_in = create_access_token(email)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)):
    email = payload.email.lower().strip()
    _login_limiter.check(f"login:{email}")

    started = time.monotonic()
    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()

    if user is None:
        verify_password(payload.password, _DUMMY_HASH)  # equalise timing
        ok = False
    else:
        ok = user.is_active and verify_password(payload.password, user.password_hash)

    # Floor the response at 150ms; a fast reject is itself a signal.
    elapsed = time.monotonic() - started
    if elapsed < 0.15:
        time.sleep(0.15 - elapsed)

    if not ok:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token, expires_in = create_access_token(email)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut(id=user.id, email=user.email, is_active=user.is_active)
