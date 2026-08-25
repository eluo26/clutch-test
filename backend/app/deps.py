"""Shared FastAPI dependencies: current user, rate limiting."""

from __future__ import annotations

import time
from collections import defaultdict, deque

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import User
from app.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> User:
    if creds is None or not creds.credentials:
        raise CREDENTIALS_ERROR
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise CREDENTIALS_ERROR from None

    email = payload.get("sub")
    if not email:
        raise CREDENTIALS_ERROR

    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise CREDENTIALS_ERROR
    return user


class RateLimiter:
    """Fixed-window-free sliding rate limiter, per key, in process memory.

    Good enough for a single-process deployment. Swap for Redis if you ever
    run more than one worker.
    """

    def __init__(self, max_calls: int, window_seconds: float = 60.0) -> None:
        self.max_calls = max_calls
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.max_calls:
            retry = int(self.window - (now - q[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Slow down.",
                headers={"Retry-After": str(retry)},
            )
        q.append(now)


_nlq_limiter = RateLimiter(get_settings().nlq_rate_limit_per_minute)


def nlq_rate_limit(
    request: Request, user: User = Depends(get_current_user)
) -> User:
    del request  # keyed on the user, not the IP
    _nlq_limiter.check(f"user:{user.id}")
    return user
