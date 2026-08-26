"""Startup work: seed an empty database, ensure the demo account exists.

Both steps exist for the deployed container, where the disk starts empty on
every deploy and nobody is around to run the ingest CLI by hand. Both are
no-ops unless explicitly switched on, so local development is unaffected.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT, get_settings
from app.models import Game, User

log = logging.getLogger(__name__)

SAMPLE_DIR = BACKEND_ROOT / "data" / "sample"


def seed_if_empty(session: Session) -> int:
    """Load the bundled fixtures when there are no games. Returns games added."""
    settings = get_settings()
    if not settings.auto_seed:
        return 0

    existing = session.execute(select(func.count()).select_from(Game)).scalar_one()
    if existing:
        log.info("database already holds %d games; skipping auto-seed", existing)
        return 0

    # Imported here rather than at module scope: the ingest package pulls in
    # the simulator, which nothing else in the request path needs.
    from app.ingest import loader
    from app.ingest.teams_static import TEAMS

    fixtures = sorted(SAMPLE_DIR.glob("*.json*"))
    if not fixtures:
        log.warning("auto-seed requested but no fixtures found in %s", SAMPLE_DIR)
        return 0

    loader.upsert_teams(session, TEAMS)
    total = 0
    for path in fixtures:
        total += loader.load_games(session, loader.read_fixture(path))
    log.info("auto-seeded %d games from %d fixture file(s)", total, len(fixtures))
    return total


def ensure_demo_user(session: Session) -> bool:
    """Create the shared read-only demo account if configured. Idempotent.

    The password comes from the environment and is deliberately *not*
    generated, because the whole point is that it can be printed on the login
    page. Treat it as public.
    """
    settings = get_settings()
    demo = settings.demo_account
    if demo is None:
        return False

    email, password = demo
    if session.execute(
        select(User).where(User.email == email)
    ).scalar_one_or_none() is not None:
        return True

    from app.security import PasswordPolicyError, hash_password

    try:
        session.add(User(email=email, password_hash=hash_password(password)))
        session.commit()
    except PasswordPolicyError as exc:
        session.rollback()
        log.error("demo account not created: %s", exc)
        return False
    except IntegrityError:
        # Another worker won the race; that is fine.
        session.rollback()
        return True

    log.info("created demo account %s", email)
    return True


def run(session_factory) -> None:
    """Run every startup step. Never raises.

    A failure here must not stop the API from serving: the realistic failure
    modes (an unreachable database, a half-written fixture) still leave an app
    that can report its own health and return a sensible error, which is far
    more useful than a container that will not boot.

    Opening the session is inside the guard too — that is the step most likely
    to fail when the database is the problem.
    """
    session = None
    try:
        session = session_factory()
        seed_if_empty(session)
        ensure_demo_user(session)
    except Exception:  # noqa: BLE001
        log.exception("startup bootstrap failed; continuing without it")
        if session is not None:
            session.rollback()
    finally:
        if session is not None:
            session.close()
