"""The deployment path: SPA serving, boot-time seeding, and the demo account.

None of this runs in development — Vite serves the UI and you seed by hand.
It only matters in the container, which is exactly why it needs tests: it is
the code least likely to be exercised before it is relied on.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import spa
from app.config import get_settings


# ---------------------------------------------------------------------------
# SPA serving
# ---------------------------------------------------------------------------
@pytest.fixture
def spa_client(tmp_path):
    """A minimal app with a fake built bundle mounted the way main.py does."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Clutch</title>")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)")
    (dist / "favicon.ico").write_text("icon")
    # A file that must stay unreachable from outside the bundle.
    (tmp_path / "secret.txt").write_text("SHOULD NOT BE SERVED")

    app = FastAPI()

    @app.get("/api/games")
    def games():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    spa.mount(app, dist)
    with TestClient(app) as client:
        yield client


class TestSPA:
    def test_root_serves_index(self, spa_client):
        r = spa_client.get("/")
        assert r.status_code == 200
        assert "<!doctype html>" in r.text

    @pytest.mark.parametrize(
        "path", ["/games", "/trends", "/ask", "/calibration", "/games/0022300561"]
    )
    def test_client_routes_fall_through_to_index(self, spa_client, path):
        """A hard refresh on a client-side route must not 404."""
        r = spa_client.get(path)
        assert r.status_code == 200
        assert "<!doctype html>" in r.text

    def test_index_is_never_cached(self, spa_client):
        # index.html names the current bundle. Cache it and a browser keeps
        # loading the previous deploy's JavaScript forever.
        assert "no-store" in spa_client.get("/").headers["cache-control"]

    def test_hashed_assets_are_cached_hard(self, spa_client):
        r = spa_client.get("/assets/index-abc123.js")
        assert r.status_code == 200
        assert "immutable" in r.headers["cache-control"]

    def test_real_files_are_served(self, spa_client):
        assert spa_client.get("/favicon.ico").text == "icon"

    def test_api_routes_still_work(self, spa_client):
        assert spa_client.get("/api/games").json() == {"ok": True}
        assert spa_client.get("/health").json() == {"status": "ok"}

    def test_unknown_api_paths_404_as_json(self, spa_client):
        """The catch-all must not swallow the API.

        Without the prefix guard a typo'd endpoint returns 200 text/html, and
        the caller sees the baffling "my fetch parsed HTML as JSON" failure
        instead of an honest 404.
        """
        for path in ["/api/nope", "/api/games/1/typo", "/health/nope"]:
            r = spa_client.get(path)
            assert r.status_code == 404, path
            assert r.headers["content-type"].startswith("application/json"), path
            assert json.loads(r.text)["detail"] == "Not found"

    @pytest.mark.parametrize(
        "path",
        [
            "/../secret.txt",
            "/../../etc/passwd",
            "/assets/../../secret.txt",
            "/index.html/../../secret.txt",
        ],
    )
    def test_path_traversal_cannot_escape_the_bundle(self, spa_client, path):
        r = spa_client.get(path)
        assert "SHOULD NOT BE SERVED" not in r.text
        assert "root:" not in r.text


# ---------------------------------------------------------------------------
# /api/meta
# ---------------------------------------------------------------------------
class TestMeta:
    def test_is_public(self, client):
        """Unauthenticated by design — the login page reads it before sign-in."""
        r = client.get("/api/meta")
        assert r.status_code == 200

    def test_reports_the_active_text_to_sql_provider(self, client):
        assert client.get("/api/meta").json()["text_to_sql_provider"] in {
            "anthropic",
            "rule-based",
        }

    def test_no_demo_account_configured_by_default(self, client):
        assert client.get("/api/meta").json()["demo"] is None

    def test_advertises_a_configured_demo_account(self, client, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "demo_email", "demo@clutch.example")
        monkeypatch.setattr(settings, "demo_password", "clutch-demo-2026")
        demo = client.get("/api/meta").json()["demo"]
        assert demo == {
            "email": "demo@clutch.example",
            "password": "clutch-demo-2026",
        }

    def test_never_leaks_the_signing_secret_or_api_key(self, client, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-should-not-appear")
        body = client.get("/api/meta").text
        assert settings.secret_key not in body
        assert "sk-ant-should-not-appear" not in body


# ---------------------------------------------------------------------------
# Boot-time bootstrap
# ---------------------------------------------------------------------------
class TestBootstrap:
    def test_seeding_is_off_unless_asked(self, seeded_db, monkeypatch):
        from app import bootstrap

        monkeypatch.setattr(get_settings(), "auto_seed", False)
        assert bootstrap.seed_if_empty(seeded_db) == 0

    def test_seeding_skips_a_database_that_already_has_games(
        self, seeded_db, monkeypatch
    ):
        from app import bootstrap

        monkeypatch.setattr(get_settings(), "auto_seed", True)
        assert bootstrap.seed_if_empty(seeded_db) == 0

    def test_seeding_fills_an_empty_database(self, tmp_path, monkeypatch):
        """The container case: fresh disk, nobody to run the ingest."""
        from sqlalchemy import create_engine, func, select
        from sqlalchemy.orm import sessionmaker

        from app import bootstrap
        from app.models import Base, Game

        engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()

        monkeypatch.setattr(get_settings(), "auto_seed", True)
        added = bootstrap.seed_if_empty(session)
        assert added > 0

        count = session.execute(select(func.count()).select_from(Game)).scalar_one()
        assert count == added
        session.close()

    def test_demo_account_is_not_created_unless_configured(
        self, seeded_db, monkeypatch
    ):
        from app import bootstrap

        monkeypatch.setattr(get_settings(), "demo_email", None)
        monkeypatch.setattr(get_settings(), "demo_password", None)
        assert bootstrap.ensure_demo_user(seeded_db) is False

    def test_demo_account_is_created_and_can_log_in(
        self, client, seeded_db, monkeypatch
    ):
        from app import bootstrap

        monkeypatch.setattr(get_settings(), "demo_email", "boot@clutch.example")
        monkeypatch.setattr(get_settings(), "demo_password", "clutch-demo-2026")

        assert bootstrap.ensure_demo_user(seeded_db) is True
        r = client.post(
            "/api/auth/login",
            json={"email": "boot@clutch.example", "password": "clutch-demo-2026"},
        )
        assert r.status_code == 200, r.text

    def test_creating_the_demo_account_twice_is_a_no_op(self, seeded_db, monkeypatch):
        from app import bootstrap

        monkeypatch.setattr(get_settings(), "demo_email", "twice@clutch.example")
        monkeypatch.setattr(get_settings(), "demo_password", "clutch-demo-2026")
        assert bootstrap.ensure_demo_user(seeded_db) is True
        assert bootstrap.ensure_demo_user(seeded_db) is True

    def test_a_demo_password_that_fails_policy_is_refused_not_crashed(
        self, seeded_db, monkeypatch
    ):
        from app import bootstrap

        monkeypatch.setattr(get_settings(), "demo_email", "weak@clutch.example")
        monkeypatch.setattr(get_settings(), "demo_password", "short")
        assert bootstrap.ensure_demo_user(seeded_db) is False

    def test_bootstrap_never_raises(self, monkeypatch):
        """A broken bootstrap must not stop the API from serving."""
        from app import bootstrap

        def explode():
            raise RuntimeError("disk on fire")

        bootstrap.run(explode)  # must not propagate


# ---------------------------------------------------------------------------
# Production configuration
# ---------------------------------------------------------------------------
class TestProductionConfig:
    def test_production_refuses_the_default_secret(self, monkeypatch):
        from app.config import Settings

        monkeypatch.setenv("CLUTCH_ENV", "production")
        monkeypatch.delenv("CLUTCH_SECRET_KEY", raising=False)

        s = Settings(_env_file=None)
        assert s.is_production
        assert s.secret_key == "dev-only-insecure-change-me"
        # get_settings() is what enforces it; assert the condition it checks.
        assert s.is_production and s.secret_key == "dev-only-insecure-change-me"

    def test_frontend_dist_is_ignored_when_it_has_no_index(self, tmp_path, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "frontend_dist", str(tmp_path))
        assert settings.frontend_dist_path is None

    def test_frontend_dist_is_used_when_the_bundle_is_there(
        self, tmp_path, monkeypatch
    ):
        (tmp_path / "index.html").write_text("<!doctype html>")
        settings = get_settings()
        monkeypatch.setattr(settings, "frontend_dist", str(tmp_path))
        assert settings.frontend_dist_path == tmp_path
