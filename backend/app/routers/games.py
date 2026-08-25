"""Game listing, detail, and win-probability endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import get_current_user
from app.models import Game, Play, User
from app.schemas import (
    GameSummary,
    LiveStateRequest,
    LiveStateResponse,
    TeamOut,
    WinProbResponse,
)
from app.winprob import service as wp_service
from app.winprob.brownian import leverage
from app.winprob.sim_client import get_sim_client

router = APIRouter(prefix="/api/games", tags=["games"])


def _summary(game: Game) -> GameSummary:
    return GameSummary(
        id=game.id,
        season=game.season,
        game_date=game.game_date,
        home=TeamOut(
            id=game.home_team.id,
            abbreviation=game.home_team.abbreviation,
            full_name=game.home_team.full_name,
        ),
        away=TeamOut(
            id=game.away_team.id,
            abbreviation=game.away_team.abbreviation,
            full_name=game.away_team.full_name,
        ),
        home_score=game.home_score,
        away_score=game.away_score,
        periods=game.periods,
    )


@router.get("", response_model=list[GameSummary])
def list_games(
    season: str | None = None,
    team: str | None = Query(default=None, description="Team abbreviation, e.g. BOS"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    stmt = select(Game).order_by(Game.game_date.desc(), Game.id.desc())
    if season:
        stmt = stmt.where(Game.season == season)
    games = session.execute(stmt.limit(limit * 4)).scalars().all()

    if team:
        team = team.upper()
        games = [
            g
            for g in games
            if team in {g.home_team.abbreviation, g.away_team.abbreviation}
        ]
    return [_summary(g) for g in games[offset : offset + limit]]


@router.get("/{game_id}", response_model=GameSummary)
def get_game(
    game_id: str,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    game = session.get(Game, game_id)
    if game is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Game not found.")
    return _summary(game)


@router.get("/{game_id}/plays")
def get_plays(
    game_id: str,
    limit: int = Query(default=500, ge=1, le=2000),
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    game = session.get(Game, game_id)
    if game is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Game not found.")
    plays = (
        session.execute(
            select(Play)
            .where(Play.game_id == game_id)
            .order_by(Play.event_num)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [
        {
            "event_num": p.event_num,
            "period": p.period,
            "clock": p.clock,
            "seconds_remaining": p.seconds_remaining,
            "event_type": p.event_type,
            "description": p.description,
            "player_name": p.player_name,
            "home_score": p.home_score,
            "away_score": p.away_score,
            "score_margin": p.score_margin,
            "points": p.points,
        }
        for p in plays
    ]


@router.get("/{game_id}/win-probability", response_model=WinProbResponse)
def win_probability(
    game_id: str,
    model: str = Query(default="blend", pattern="^(brownian|markov|blend)$"),
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    game = session.get(Game, game_id)
    if game is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Game not found.")

    params = wp_service.fit_params(session, game.season)
    points = wp_service.win_probability_path(session, game_id, model=model, params=params)  # type: ignore[arg-type]
    if not points:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No play-by-play rows for this game. Run the ingest first.",
        )
    return WinProbResponse(
        game=_summary(game),
        model=model,
        params=params.as_dict(),
        points=[p.as_dict() for p in points],  # type: ignore[arg-type]
    )


@router.post("/win-probability/state", response_model=LiveStateResponse)
def state_win_probability(
    payload: LiveStateRequest,
    season: str | None = None,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Score an arbitrary game state -- the "what if" slider in the UI."""
    params = wp_service.fit_params(session, season)
    source = "python"
    if payload.model == "markov" and payload.use_java_sim:
        from app.winprob.markov import possessions_remaining

        result = get_sim_client().win_probability(
            payload.margin,
            possessions_remaining(payload.seconds_remaining),
            True if payload.home_has_ball is None else payload.home_has_ball,
        )
        wp, source = result.win_probability, result.source
    else:
        wp = wp_service.score_state(
            payload.margin,
            payload.seconds_remaining,
            model=payload.model,
            params=params,
            home_has_ball=payload.home_has_ball,
        )
    return LiveStateResponse(
        win_probability=round(wp, 4),
        leverage=round(leverage(payload.margin, payload.seconds_remaining, params), 4),
        model=payload.model,
        source=source,
    )
