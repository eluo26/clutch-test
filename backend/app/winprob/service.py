"""Ties the models to the database: fitting, win-prob paths, backtests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Game, Play
from app.winprob import calibration, clock, markov
from app.winprob.brownian import (
    REGULATION_SECONDS,
    BrownianParams,
    fit_brownian_params,
    leverage,
)
from app.winprob.brownian import (
    win_probability as brownian_wp,
)
from app.winprob.sim_client import get_sim_client

ModelName = Literal["brownian", "markov", "blend"]

# Below this many seconds the discrete possession structure dominates and the
# Markov chain carries full weight; above it the diffusion approximation is
# fine. In between we cross-fade.
BLEND_START_SECONDS = 360.0


@dataclass
class WinProbPoint:
    event_num: int
    period: int
    clock: str
    seconds_remaining: int
    home_score: int
    away_score: int
    margin: int
    description: str
    win_probability: float
    leverage: float

    def as_dict(self) -> dict:
        return {
            "event_num": self.event_num,
            "period": self.period,
            "clock": self.clock,
            "seconds_remaining": self.seconds_remaining,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "margin": self.margin,
            "description": self.description,
            "win_probability": round(self.win_probability, 4),
            "leverage": round(self.leverage, 4),
        }


# --------------------------------------------------------------------------
# Parameter fitting
# --------------------------------------------------------------------------


def fit_params(session: Session, season: str | None = None) -> BrownianParams:
    stmt = select(Game.home_score, Game.away_score)
    if season:
        stmt = stmt.where(Game.season == season)
    rows = session.execute(stmt).all()
    margins = [float(h - a) for h, a in rows]
    return fit_brownian_params(margins)


def fit_possession_model(
    session: Session, season: str | None = None
) -> markov.PossessionModel:
    """Estimate the per-trip scoring distribution from the ingested data.

    The denominator is the count of *trips* -- ``FGA + 0.44*FTA + TOV`` -- and
    not the box-score possession count, because that is what one step of the
    chain represents (see the module docstring in ``markov.py``). Dividing by
    possessions instead inflates every rate by roughly 10% and pushes the
    implied points per possession up around 1.3, which is the tell that this
    has been got wrong.

    Falls back to league-average defaults when there is too little data, or
    when the fit lands somewhere implausible.
    """
    box_stmt = select(
        func.sum(Game.home_fga + Game.away_fga),
        func.sum(Game.home_fta + Game.away_fta),
        func.sum(Game.home_tov + Game.away_tov),
        func.sum(Game.home_oreb + Game.away_oreb),
    )
    if season:
        box_stmt = box_stmt.where(Game.season == season)
    fga, fta, tov, oreb = session.execute(box_stmt).one()
    if not fga:
        return markov.DEFAULT_POSSESSION_MODEL

    trips = float(fga) + 0.44 * float(fta or 0) + float(tov or 0)
    if trips < 500:
        return markov.DEFAULT_POSSESSION_MODEL

    play_stmt = select(Play.points, Play.event_type)
    if season:
        play_stmt = play_stmt.join(Game, Game.id == Play.game_id).where(
            Game.season == season
        )
    rows = session.execute(play_stmt).all()

    made_three = sum(1 for p, t in rows if t == "SHOT" and p == 3)
    made_two = sum(1 for p, t in rows if t == "SHOT" and p == 2)
    ft_points = sum(p for p, t in rows if t == "FREE_THROW")

    # Free-throw points per trip, split into one- and two-point outcomes in the
    # usual 2:1 ratio (``2 * 0.4x + 1 * 0.2x == x``).
    ft_per_trip = ft_points / trips
    misses = max(1.0, float(fga) - made_three - made_two)

    model = markov.PossessionModel(
        p_three=round(made_three / trips, 4),
        p_two=round(made_two / trips, 4),
        p_and_one=markov.DEFAULT_POSSESSION_MODEL.p_and_one,
        p_two_ft=round(0.4 * ft_per_trip, 4),
        p_one_ft=round(0.2 * ft_per_trip, 4),
        oreb_prob=round(min(0.4, float(oreb or 0) / misses), 4),
    )

    # Sanity gate. A fit outside this band means the ingested data is shaped
    # differently than assumed; better league average than nonsense.
    if not (0.85 < model.points_per_possession < 1.45) or model.p_empty <= 0.2:
        return markov.DEFAULT_POSSESSION_MODEL
    return model


# --------------------------------------------------------------------------
# Scoring a single game state
# --------------------------------------------------------------------------


def score_state(
    margin: int,
    seconds_remaining: float,
    model: ModelName = "blend",
    params: BrownianParams | None = None,
    home_has_ball: bool | None = None,
    use_java_sim: bool = False,
) -> float:
    params = params or BrownianParams()
    has_ball = True if home_has_ball is None else home_has_ball

    state = clock.resolve(margin, seconds_remaining)
    if state.is_over:
        return 1.0 if margin > 0 else 0.0

    if model == "brownian":
        return brownian_wp(margin, seconds_remaining, params, home_has_ball)

    if model == "markov":
        k = markov.trips_remaining(state.seconds_left)
        if use_java_sim:
            return get_sim_client().win_probability(margin, k, has_ball).win_probability
        return markov.default_solver().win_probability(margin, k, has_ball)

    # Blend: diffusion early, chain late, linear cross-fade between. Overtime
    # sits entirely inside the late window and so is scored by the chain --
    # which is right, since five minutes is squarely the regime where the
    # discrete possession structure dominates.
    if state.seconds_left >= BLEND_START_SECONDS and not state.is_overtime:
        return brownian_wp(margin, seconds_remaining, params, home_has_ball)
    w = max(0.0, min(1.0, state.seconds_left / BLEND_START_SECONDS))
    b = brownian_wp(margin, seconds_remaining, params, home_has_ball)
    m = markov.default_solver().win_probability(
        margin, markov.trips_remaining(state.seconds_left), has_ball
    )
    return w * b + (1.0 - w) * m


# --------------------------------------------------------------------------
# Whole-game win probability path
# --------------------------------------------------------------------------


def win_probability_path(
    session: Session,
    game_id: str,
    model: ModelName = "blend",
    params: BrownianParams | None = None,
) -> list[WinProbPoint]:
    params = params or fit_params(session)
    plays = (
        session.execute(
            select(Play).where(Play.game_id == game_id).order_by(Play.event_num)
        )
        .scalars()
        .all()
    )

    points: list[WinProbPoint] = []
    for play in plays:
        has_ball = None
        if play.team_id is not None:
            game = play.game
            has_ball = play.team_id == game.home_team_id
        wp = score_state(
            play.score_margin,
            play.seconds_remaining,
            model=model,
            params=params,
            home_has_ball=has_ball,
        )
        points.append(
            WinProbPoint(
                event_num=play.event_num,
                period=play.period,
                clock=play.clock,
                seconds_remaining=play.seconds_remaining,
                home_score=play.home_score,
                away_score=play.away_score,
                margin=play.score_margin,
                description=play.description,
                win_probability=wp,
                leverage=leverage(play.score_margin, play.seconds_remaining, params),
            )
        )
    return points


# --------------------------------------------------------------------------
# Backtesting
# --------------------------------------------------------------------------


@dataclass
class BacktestResult:
    model: ModelName
    params: dict
    overall: dict
    by_time: dict
    n_games: int
    n_forecasts: int

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "params": self.params,
            "n_games": self.n_games,
            "n_forecasts": self.n_forecasts,
            "overall": self.overall,
            "by_time": self.by_time,
        }


def backtest(
    session: Session,
    model: ModelName = "blend",
    season: str | None = None,
    game_ids: Sequence[str] | None = None,
    stride_seconds: int = 30,
    fit_on: str | None = None,
    n_bins: int = 10,
) -> BacktestResult:
    """Score every game state on a fixed clock grid and report calibration.

    Sampling on a clock grid rather than per-event matters: events cluster
    around free throws and timeouts, so per-event sampling silently
    over-weights those moments.

    ``fit_on`` names a season used to fit ``mu``/``sigma``; leave it ``None``
    to fit on the same games being scored (in-sample -- fine for a smoke test,
    not for a headline number).
    """
    params = fit_params(session, fit_on) if fit_on else fit_params(session, season)

    stmt = select(Game)
    if season:
        stmt = stmt.where(Game.season == season)
    if game_ids:
        stmt = stmt.where(Game.id.in_(list(game_ids)))
    games = session.execute(stmt).scalars().all()

    records: list[tuple[float, int, float]] = []
    for game in games:
        outcome = 1 if game.home_score > game.away_score else 0
        plays = (
            session.execute(
                select(Play).where(Play.game_id == game.id).order_by(Play.event_num)
            )
            .scalars()
            .all()
        )
        if not plays:
            continue

        # Walk the clock downward, taking the most recent play at each tick.
        # The grid stops short of 0: at the buzzer the outcome is already
        # settled, so scoring it would hand every model a free perfect
        # forecast and flatter the Brier score. Overtime is excluded for the
        # same reason -- it is only reachable from a tie, where every model
        # says 50%.
        idx = 0
        for secs in range(REGULATION_SECONDS - stride_seconds, 0, -stride_seconds):
            while idx + 1 < len(plays) and plays[idx + 1].seconds_remaining >= secs:
                idx += 1
            play = plays[idx]
            if play.seconds_remaining < secs:
                continue
            has_ball = (
                None if play.team_id is None else play.team_id == game.home_team_id
            )
            p = score_state(
                play.score_margin, secs, model=model, params=params, home_has_ball=has_ball
            )
            records.append((p, outcome, float(secs)))

    probs = [r[0] for r in records]
    ys = [r[1] for r in records]
    return BacktestResult(
        model=model,
        params=params.as_dict(),
        overall=calibration.evaluate(probs, ys, n_bins).as_dict(),
        by_time=calibration.evaluate_by_time_bucket(records),
        n_games=len(games),
        n_forecasts=len(records),
    )
