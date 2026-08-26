"""Application settings, loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"), env_prefix="CLUTCH_", extra="ignore"
    )

    # --- storage -------------------------------------------------------
    database_url: str = f"sqlite:///{BACKEND_ROOT / 'clutch.db'}"

    # --- auth ----------------------------------------------------------
    # Override in production. The app refuses to start with the default
    # value unless CLUTCH_ENV=dev.
    secret_key: str = "dev-only-insecure-change-me"
    env: str = "dev"
    access_token_ttl_minutes: int = 60 * 12
    min_password_length: int = 10

    # --- LLM / text-to-SQL ---------------------------------------------
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5"
    nlq_row_limit: int = 500
    nlq_timeout_seconds: float = 20.0
    nlq_rate_limit_per_minute: int = 10

    # --- Java Markov simulator ------------------------------------------
    # When unreachable the API silently falls back to the pure-Python
    # solver in app/winprob/markov.py, so the service is optional.
    sim_service_url: str = "http://127.0.0.1:8081"
    sim_service_timeout_seconds: float = 3.0

    # --- CORS ------------------------------------------------------------
    # Only relevant in development, where Vite serves the UI on another port.
    # In the deployed container one process serves both, so the browser never
    # makes a cross-origin request and this list goes unused.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- deployment ------------------------------------------------------
    # Load the bundled sample fixtures at startup when the database has no
    # games. Off locally (you run the ingest yourself); on in the container,
    # where the disk starts empty on every deploy.
    auto_seed: bool = False

    # An optional shared read-only account, so someone can look around the
    # deployed site without signing up. Both must be set for it to exist.
    demo_email: str | None = None
    demo_password: str | None = None

    # Directory holding the built React bundle. When present, FastAPI serves
    # the UI itself and the whole app is one process on one port.
    frontend_dist: str = str(REPO_ROOT / "frontend" / "dist")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def frontend_dist_path(self) -> Path | None:
        path = Path(self.frontend_dist)
        return path if (path / "index.html").is_file() else None

    @property
    def demo_account(self) -> tuple[str, str] | None:
        if self.demo_email and self.demo_password:
            return self.demo_email.lower().strip(), self.demo_password
        return None

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"prod", "production"}


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_production and s.secret_key == "dev-only-insecure-change-me":
        raise RuntimeError(
            "CLUTCH_SECRET_KEY must be set to a real secret when CLUTCH_ENV=production"
        )
    return s
