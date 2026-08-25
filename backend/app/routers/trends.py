"""League-wide trend aggregations and forward projection."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import get_current_user
from app.models import Game, User
from app.schemas import SeasonTrend, TrendsResponse

router = APIRouter(prefix="/api/trends", tags=["trends"])

MINUTES_PER_GAME = 48.0


@router.get("/seasons", response_model=TrendsResponse)
def season_trends(
    session: Session = Depends(get_session), _: User = Depends(get_current_user)
):
    """Pace, efficiency, and three-point volume by season."""
    rows = session.execute(
        select(
            Game.season,
            func.count(Game.id),
            func.sum(Game.home_score + Game.away_score),
            func.sum(Game.home_fga + Game.away_fga),
            func.sum(Game.home_fg3a + Game.away_fg3a),
            func.sum(Game.home_fg3m + Game.away_fg3m),
            func.sum(Game.home_fta + Game.away_fta),
            func.sum(Game.home_oreb + Game.away_oreb),
            func.sum(Game.home_tov + Game.away_tov),
            func.sum(case((Game.home_score > Game.away_score, 1), else_=0)),
        )
        .group_by(Game.season)
        .order_by(Game.season)
    ).all()

    seasons: list[SeasonTrend] = []
    for (
        season,
        n,
        pts,
        fga,
        fg3a,
        fg3m,
        fta,
        oreb,
        tov,
        home_wins,
    ) in rows:
        if not n:
            continue
        possessions = (fga or 0) + 0.44 * (fta or 0) - (oreb or 0) + (tov or 0)
        # Both teams' possessions summed; per-team pace is half of that.
        pace = (possessions / n) / 2.0
        seasons.append(
            SeasonTrend(
                season=season,
                games=n,
                pace=round(pace, 2),
                points_per_100=round(
                    100.0 * (pts or 0) / possessions if possessions else 0.0, 2
                ),
                three_point_rate=round((fg3a or 0) / fga, 4) if fga else 0.0,
                three_point_pct=round((fg3m or 0) / fg3a, 4) if fg3a else 0.0,
                avg_total_points=round((pts or 0) / n, 2),
                home_win_rate=round((home_wins or 0) / n, 4),
            )
        )
    return TrendsResponse(seasons=seasons)


@router.get("/project")
def project(
    metric: str = Query(
        default="three_point_rate",
        pattern="^(three_point_rate|pace|points_per_100|avg_total_points)$",
    ),
    horizon: int = Query(default=3, ge=1, le=10),
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Project a league metric forward with an OLS trend line.

    Deliberately the simplest defensible thing: fit ``y = a + b*t`` over the
    observed seasons and extend it, reporting the residual standard error so
    the band is honest about how little the fit knows. A three-season
    extrapolation of a league trend is a trend line, not a forecast, and the
    response says so.
    """
    trends = season_trends(session=session, _=None).seasons  # type: ignore[arg-type]
    series = [(i, getattr(t, metric)) for i, t in enumerate(trends)]
    if len(series) < 2:
        return {
            "metric": metric,
            "observed": [],
            "projected": [],
            "note": "Need at least two seasons of data to fit a trend.",
        }

    n = len(series)
    mean_x = sum(x for x, _ in series) / n
    mean_y = sum(y for _, y in series) / n
    sxx = sum((x - mean_x) ** 2 for x, _ in series)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in series)
    slope = sxy / sxx if sxx else 0.0
    intercept = mean_y - slope * mean_x

    resid = [y - (intercept + slope * x) for x, y in series]
    dof = max(1, n - 2)
    se = (sum(r * r for r in resid) / dof) ** 0.5

    last_season = trends[-1].season
    start_year = int(last_season.split("-")[0])
    projected = []
    for h in range(1, horizon + 1):
        x = n - 1 + h
        y = intercept + slope * x
        yr = start_year + h
        projected.append(
            {
                "season": f"{yr}-{str(yr + 1)[-2:]}",
                "value": round(y, 4),
                "lower": round(y - 1.96 * se, 4),
                "upper": round(y + 1.96 * se, 4),
            }
        )

    return {
        "metric": metric,
        "slope_per_season": round(slope, 5),
        "residual_std_error": round(se, 5),
        "observed": [
            {"season": t.season, "value": getattr(t, metric)} for t in trends
        ],
        "projected": projected,
        "note": (
            "Linear trend extrapolation, not a forecast. The band is +/-1.96 "
            "residual standard errors and ignores rule changes, which are the "
            "main thing that actually moves these curves."
        ),
    }
