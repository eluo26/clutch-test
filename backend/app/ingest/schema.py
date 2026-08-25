"""The normalized intermediate format shared by every data source.

Both the live nba_api ingest and the synthetic fixture generator emit this
shape, and the loader only ever sees this. That separation is what lets the
test suite and a fresh clone run with zero network calls while the production
path pulls real games.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

REGULATION_SECONDS = 48 * 60
PERIOD_SECONDS = 12 * 60
OT_SECONDS = 5 * 60


@dataclass
class TeamRecord:
    id: int
    abbreviation: str
    full_name: str
    conference: str | None = None


@dataclass
class PlayRecord:
    event_num: int
    period: int
    clock: str
    seconds_remaining: int
    event_type: str
    description: str
    team_id: int | None
    player_name: str | None
    home_score: int
    away_score: int
    score_margin: int
    points: int = 0
    shot_distance: float | None = None
    is_three: bool = False


@dataclass
class PlayerBoxRecord:
    team_id: int
    player_name: str
    minutes: float
    points: int
    rebounds: int
    assists: int
    fg3a: int
    fg3m: int


@dataclass
class GameRecord:
    id: str
    season: str
    season_type: str
    game_date: str
    home_team_id: int
    away_team_id: int
    home_score: int
    away_score: int
    periods: int
    home_fga: int = 0
    home_fg3a: int = 0
    home_fg3m: int = 0
    home_fta: int = 0
    home_oreb: int = 0
    home_tov: int = 0
    away_fga: int = 0
    away_fg3a: int = 0
    away_fg3m: int = 0
    away_fta: int = 0
    away_oreb: int = 0
    away_tov: int = 0
    plays: list[PlayRecord] = field(default_factory=list)
    player_box: list[PlayerBoxRecord] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> GameRecord:
        plays = [PlayRecord(**p) for p in data.pop("plays", [])]
        box = [PlayerBoxRecord(**b) for b in data.pop("player_box", [])]
        return cls(**data, plays=plays, player_box=box)


def seconds_remaining(period: int, clock_seconds: float) -> int:
    """Seconds left in regulation. Negative once overtime starts.

    Overtime is measured as time *past* the end of regulation, so a single
    monotone axis runs from 2880 at tip-off through 0 at the buzzer and on
    into negative numbers -- which is exactly what the win-probability models
    want.
    """
    if period <= 4:
        return int(round((4 - period) * PERIOD_SECONDS + clock_seconds))
    elapsed_ot = (period - 5) * OT_SECONDS + (OT_SECONDS - clock_seconds)
    return -int(round(elapsed_ot))


def parse_clock(clock: str) -> float:
    """Accepts 'MM:SS', 'M:SS.s', or the ISO 'PT11M32.00S' form."""
    clock = (clock or "").strip()
    if not clock:
        return 0.0
    if clock.startswith("PT"):
        body = clock[2:]
        minutes = 0.0
        seconds = 0.0
        if "M" in body:
            m, body = body.split("M", 1)
            minutes = float(m)
        if "S" in body:
            seconds = float(body.rstrip("S"))
        return minutes * 60 + seconds
    parts = clock.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def format_clock(seconds: float) -> str:
    seconds = max(0.0, seconds)
    return f"{int(seconds // 60):d}:{int(seconds % 60):02d}"
