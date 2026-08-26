"""Clutch API entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import bootstrap, spa
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.routers import auth, calibration, games, nlq, trends

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    # Seeds an empty database and creates the demo account when configured;
    # a no-op otherwise. Never raises -- see app/bootstrap.py.
    bootstrap.run(SessionLocal)
    yield


app = FastAPI(
    title="Clutch",
    version="0.1.0",
    summary="NBA win probability, league trends, and natural-language play-by-play search.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):  # pragma: no cover
    logging.getLogger("clutch").exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


app.include_router(auth.router)
app.include_router(games.router)
app.include_router(trends.router)
app.include_router(nlq.router)
app.include_router(calibration.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "service": "clutch-api", "version": app.version}


@app.get("/api/meta", tags=["meta"])
def meta():
    """Public, unauthenticated: what this deployment offers a visitor.

    The login page reads this to decide whether to show a "try the demo
    account" button. The password is returned deliberately -- a shared
    read-only demo credential printed on the sign-in page is public by
    construction, and pretending otherwise would just mean nobody can use it.
    """
    demo = settings.demo_account
    return {
        "version": app.version,
        "text_to_sql_provider": (
            "anthropic" if settings.anthropic_api_key else "rule-based"
        ),
        "demo": (
            {"email": demo[0], "password": demo[1]} if demo is not None else None
        ),
    }


# Mounted last: the SPA catch-all must sit behind every real route.
if (_dist := settings.frontend_dist_path) is not None:
    spa.mount(app, _dist)
