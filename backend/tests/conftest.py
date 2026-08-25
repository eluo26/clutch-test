"""Test fixtures.

Every test runs against a throwaway SQLite file seeded with a handful of
synthetic games, so the suite needs no network and no external services.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Must be set before app.config is imported anywhere.
_TMP = Path(tempfile.mkdtemp(prefix="clutch-test-"))
os.environ["CLUTCH_DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["CLUTCH_SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["CLUTCH_ENV"] = "test"
os.environ.pop("CLUTCH_ANTHROPIC_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.ingest import loader, synthetic  # noqa: E402
from app.ingest.teams_static import TEAMS  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def seeded_db():
    init_db()
    session = SessionLocal()
    try:
        loader.upsert_teams(session, TEAMS)
        for season, start, shift in (
            ("2022-23T", "2022-10-18", -0.03),
            ("2023-24T", "2023-10-24", 0.0),
        ):
            games = synthetic.simulate_season(
                season,
                n_games=20,
                seed=99,
                start_date=start,
                three_rate_shift=shift,
                league_seed=4242,
            )
            loader.load_games(session, games)
        yield session
    finally:
        session.close()


@pytest.fixture(scope="session")
def client(seeded_db):
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def auth_client(client):
    """A client with a registered, logged-in user's bearer token attached."""
    email = "analyst@example.com"
    password = "correct-horse-9"
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code in (201, 409), r.text
    if r.status_code == 409:
        r = client.post("/api/auth/login", json={"email": email, "password": password})
    token = r.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    yield client
    client.headers.pop("Authorization", None)


@pytest.fixture(scope="session")
def sample_game_id(seeded_db):
    from sqlalchemy import select

    from app.models import Game

    return seeded_db.execute(select(Game.id)).scalars().first()
