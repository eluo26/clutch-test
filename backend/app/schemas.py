"""Pydantic request/response models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


# --- auth -----------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    id: int
    email: EmailStr
    is_active: bool


# --- games ----------------------------------------------------------------
class TeamOut(BaseModel):
    id: int
    abbreviation: str
    full_name: str


class GameSummary(BaseModel):
    id: str
    season: str
    game_date: str
    home: TeamOut
    away: TeamOut
    home_score: int
    away_score: int
    periods: int


class WinProbPointOut(BaseModel):
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


class WinProbResponse(BaseModel):
    game: GameSummary
    model: str
    params: dict[str, Any]
    points: list[WinProbPointOut]


class LiveStateRequest(BaseModel):
    margin: int = Field(ge=-99, le=99, description="home score minus away score")
    seconds_remaining: float = Field(ge=0, le=48 * 60)
    home_has_ball: bool | None = None
    model: Literal["brownian", "markov", "blend"] = "blend"
    use_java_sim: bool = False


class LiveStateResponse(BaseModel):
    win_probability: float
    leverage: float
    model: str
    source: str


# --- trends ---------------------------------------------------------------
class SeasonTrend(BaseModel):
    season: str
    games: int
    pace: float
    points_per_100: float
    three_point_rate: float
    three_point_pct: float
    avg_total_points: float
    home_win_rate: float


class TrendsResponse(BaseModel):
    seasons: list[SeasonTrend]


# --- natural-language query ------------------------------------------------
class NLQRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    explain: bool = True


class NLQResponse(BaseModel):
    question: str
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    provider: str
    explanation: str | None = None


# --- calibration -----------------------------------------------------------
class BacktestRequest(BaseModel):
    model: Literal["brownian", "markov", "blend"] = "blend"
    season: str | None = None
    stride_seconds: int = Field(default=30, ge=5, le=300)
    n_bins: int = Field(default=10, ge=4, le=25)
