"""Password hashing and JWT issuance/verification."""

from __future__ import annotations

import hmac
import re
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import get_settings

ALGORITHM = "HS256"

# bcrypt truncates at 72 bytes; reject longer inputs rather than silently
# ignoring the tail (which would make "<72 chars>x" and "<72 chars>y" the same
# password).
MAX_PASSWORD_BYTES = 72

# Cost factor. 12 is ~250ms on current hardware -- slow enough to matter for an
# attacker, fast enough not to be a self-inflicted denial of service.
BCRYPT_ROUNDS = 12


class PasswordPolicyError(ValueError):
    pass


def validate_password(password: str) -> None:
    settings = get_settings()
    if len(password) < settings.min_password_length:
        raise PasswordPolicyError(
            f"Password must be at least {settings.min_password_length} characters."
        )
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise PasswordPolicyError("Password must be at most 72 bytes.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise PasswordPolicyError("Password must contain both letters and a digit.")


def hash_password(password: str) -> str:
    validate_password(password)
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8")[:MAX_PASSWORD_BYTES],
            password_hash.encode("ascii"),
        )
    except Exception:  # noqa: BLE001 - a malformed stored hash must not 500
        return False


def create_access_token(subject: str, extra: dict | None = None) -> tuple[str, int]:
    """Returns ``(token, expires_in_seconds)``."""
    settings = get_settings()
    ttl = timedelta(minutes=settings.access_token_ttl_minutes)
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "typ": "access",
    }
    if extra:
        payload.update(extra)
    token = jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
    return token, int(ttl.total_seconds())


def decode_access_token(token: str) -> dict:
    """Raises ``jwt.PyJWTError`` on any problem."""
    settings = get_settings()
    payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
