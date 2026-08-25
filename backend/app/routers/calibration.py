"""Backtest / calibration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import get_current_user
from app.models import User
from app.schemas import BacktestRequest
from app.winprob import service as wp_service
from app.winprob.sim_client import get_sim_client

router = APIRouter(prefix="/api/calibration", tags=["calibration"])


@router.post("/backtest")
def run_backtest(
    payload: BacktestRequest,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    result = wp_service.backtest(
        session,
        model=payload.model,
        season=payload.season,
        stride_seconds=payload.stride_seconds,
        n_bins=payload.n_bins,
    )
    return result.as_dict()


@router.get("/compare")
def compare_models(
    season: str | None = None,
    stride_seconds: int = 30,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Run all three models over the same games so the numbers are comparable."""
    out = {}
    for model in ("brownian", "markov", "blend"):
        r = wp_service.backtest(
            session, model=model, season=season, stride_seconds=stride_seconds  # type: ignore[arg-type]
        )
        out[model] = {
            "brier": r.overall["brier"],
            "brier_skill": r.overall["brier_skill"],
            "log_loss": r.overall["log_loss"],
            "ece": r.overall["ece"],
            "n_forecasts": r.n_forecasts,
            "clutch": r.by_time.get("Clutch (final 5:00)", {}),
        }
    return {"season": season, "models": out}


@router.get("/possession-model")
def possession_model(
    season: str | None = None,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """The fitted possession-outcome distribution behind the Markov chain."""
    model = wp_service.fit_possession_model(session, season)
    return {
        "season": season,
        "model": model.as_dict(),
        "java_sim_available": get_sim_client().health(),
    }
