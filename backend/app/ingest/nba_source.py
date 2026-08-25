"""Live ingest from stats.nba.com via the ``nba_api`` package.

``nba_api`` is an optional dependency (``pip install -e '.[ingest]'``). The
endpoint is rate-limited and occasionally rude about headers, so every call
goes through :func:`_retry` with a delay -- pulling a full season without a
backoff is the fastest way to get a temporary block.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Iterator
from typing import Any

from app.ingest.schema import (
    GameRecord,
    PlayerBoxRecord,
    PlayRecord,
    TeamRecord,
    parse_clock,
    seconds_remaining,
)

log = logging.getLogger(__name__)

REQUEST_DELAY_SECONDS = 0.75
MAX_RETRIES = 4

# nba_api EVENTMSGTYPE codes.
EVENT_TYPES = {
    1: "SHOT",
    2: "MISS",
    3: "FREE_THROW",
    4: "REBOUND",
    5: "TURNOVER",
    6: "FOUL",
    7: "VIOLATION",
    8: "SUB",
    9: "TIMEOUT",
    10: "JUMP_BALL",
    11: "EJECTION",
    12: "PERIOD_START",
    13: "PERIOD_END",
}


class NBASourceUnavailable(RuntimeError):
    pass


def _require_nba_api():
    try:
        import nba_api  # noqa: F401
    except ImportError as exc:  # pragma: no cover - env dependent
        raise NBASourceUnavailable(
            "nba_api is not installed. Run: pip install -e '.[ingest]'"
        ) from exc


def _retry(fn: Callable[[], Any], what: str) -> Any:
    delay = REQUEST_DELAY_SECONDS
    last: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(delay)
            return fn()
        except Exception as exc:  # noqa: BLE001 - the client raises many types
            last = exc
            delay *= 2
            log.warning("%s failed (attempt %d/%d): %s", what, attempt + 1, MAX_RETRIES, exc)
    raise NBASourceUnavailable(f"{what} failed after {MAX_RETRIES} attempts: {last}")


# ---------------------------------------------------------------------------
def fetch_teams() -> list[TeamRecord]:
    _require_nba_api()
    from nba_api.stats.static import teams as static_teams

    return [
        TeamRecord(
            id=int(t["id"]),
            abbreviation=t["abbreviation"],
            full_name=t["full_name"],
        )
        for t in static_teams.get_teams()
    ]


def list_game_ids(season: str, season_type: str = "Regular Season") -> list[str]:
    """Distinct game ids for a season, e.g. ``list_game_ids('2023-24')``."""
    _require_nba_api()
    from nba_api.stats.endpoints import leaguegamefinder

    def call():
        return leaguegamefinder.LeagueGameFinder(
            season_nullable=season,
            season_type_nullable=season_type,
            league_id_nullable="00",
        ).get_data_frames()[0]

    df = _retry(call, f"leaguegamefinder({season})")
    return sorted({str(g) for g in df["GAME_ID"].tolist()})


def _shot_points(description: str, event_code: int) -> tuple[int, bool]:
    desc = (description or "").upper()
    is_three = "3PT" in desc
    if event_code == 1:
        return (3 if is_three else 2), is_three
    if event_code == 2:
        return 0, is_three
    if event_code == 3:
        return (0 if "MISS" in desc else 1), False
    return 0, False


def _shot_distance(description: str) -> float | None:
    desc = (description or "").upper()
    if "'" not in desc:
        return None
    for token in desc.replace("(", " ").replace(")", " ").split():
        if token.endswith("'") and token[:-1].isdigit():
            return float(token[:-1])
    return None


def fetch_game(game_id: str, season: str, season_type: str = "Regular Season") -> GameRecord:
    """Pull play-by-play and box score for one game into a :class:`GameRecord`."""
    _require_nba_api()
    from nba_api.stats.endpoints import boxscoretraditionalv2, playbyplayv2

    box = _retry(
        lambda: boxscoretraditionalv2.BoxScoreTraditionalV2(
            game_id=game_id
        ).get_data_frames(),
        f"boxscore({game_id})",
    )
    players_df, teams_df = box[0], box[1]
    if teams_df.empty:
        raise NBASourceUnavailable(f"no box score rows for {game_id}")

    # The nba_api team box lists the away team first, home team second.
    away_row, home_row = teams_df.iloc[0], teams_df.iloc[1]

    def _i(row, col) -> int:
        val = row.get(col)
        return int(val) if val == val and val is not None else 0  # NaN-safe

    record = GameRecord(
        id=game_id,
        season=season,
        season_type=season_type,
        game_date="",
        home_team_id=int(home_row["TEAM_ID"]),
        away_team_id=int(away_row["TEAM_ID"]),
        home_score=_i(home_row, "PTS"),
        away_score=_i(away_row, "PTS"),
        periods=4,
        home_fga=_i(home_row, "FGA"),
        home_fg3a=_i(home_row, "FG3A"),
        home_fg3m=_i(home_row, "FG3M"),
        home_fta=_i(home_row, "FTA"),
        home_oreb=_i(home_row, "OREB"),
        home_tov=_i(home_row, "TO"),
        away_fga=_i(away_row, "FGA"),
        away_fg3a=_i(away_row, "FG3A"),
        away_fg3m=_i(away_row, "FG3M"),
        away_fta=_i(away_row, "FTA"),
        away_oreb=_i(away_row, "OREB"),
        away_tov=_i(away_row, "TO"),
    )

    for _, r in players_df.iterrows():
        minutes = 0.0
        raw_min = r.get("MIN")
        if isinstance(raw_min, str) and ":" in raw_min:
            mm, ss = raw_min.split(":")
            minutes = int(mm) + int(ss) / 60.0
        record.player_box.append(
            PlayerBoxRecord(
                team_id=int(r["TEAM_ID"]),
                player_name=str(r["PLAYER_NAME"]),
                minutes=round(minutes, 2),
                points=_i(r, "PTS"),
                rebounds=_i(r, "REB"),
                assists=_i(r, "AST"),
                fg3a=_i(r, "FG3A"),
                fg3m=_i(r, "FG3M"),
            )
        )

    pbp = _retry(
        lambda: playbyplayv2.PlayByPlayV2(game_id=game_id).get_data_frames()[0],
        f"playbyplay({game_id})",
    )

    home_score = away_score = 0
    for _, r in pbp.iterrows():
        code = int(r["EVENTMSGTYPE"])
        period = int(r["PERIOD"])
        record.periods = max(record.periods, period)

        desc = (
            r.get("HOMEDESCRIPTION")
            or r.get("VISITORDESCRIPTION")
            or r.get("NEUTRALDESCRIPTION")
            or ""
        )
        desc = str(desc)

        score = r.get("SCORE")
        if isinstance(score, str) and "-" in score:
            away_str, home_str = score.split("-")
            away_score, home_score = int(away_str.strip()), int(home_str.strip())

        points, is_three = _shot_points(desc, code)
        team_id = r.get("PLAYER1_TEAM_ID")
        team_id = int(team_id) if team_id == team_id and team_id else None

        clock_secs = parse_clock(str(r.get("PCTIMESTRING") or "0:00"))
        record.plays.append(
            PlayRecord(
                event_num=int(r["EVENTNUM"]),
                period=period,
                clock=str(r.get("PCTIMESTRING") or "0:00"),
                seconds_remaining=seconds_remaining(period, clock_secs),
                event_type=EVENT_TYPES.get(code, "OTHER"),
                description=desc[:255],
                team_id=team_id,
                player_name=(str(r.get("PLAYER1_NAME")) if r.get("PLAYER1_NAME") else None),
                home_score=home_score,
                away_score=away_score,
                score_margin=home_score - away_score,
                points=points,
                shot_distance=_shot_distance(desc),
                is_three=is_three,
            )
        )

    return record


def fetch_games(
    game_ids: Iterable[str], season: str, season_type: str = "Regular Season"
) -> Iterator[GameRecord]:
    for gid in game_ids:
        try:
            yield fetch_game(gid, season, season_type)
        except NBASourceUnavailable as exc:
            log.error("skipping %s: %s", gid, exc)
