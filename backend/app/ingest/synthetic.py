"""Synthetic game generator.

Why this exists: calibration work needs *volume*. Backtesting a win
probability model on the handful of games you can politely pull from
stats.nba.com in a minute tells you nothing -- reliability bins need thousands
of forecasts before the observed frequencies stop being noise. This module
simulates games possession by possession so the model, the backtest, the API
and the UI can all be exercised end to end with no network at all.

The simulator is deliberately *not* the same process as either win probability
model. It works in continuous clock time with team-specific efficiency and
pace, includes overtime, and emits real play-by-play rows. So when the Markov
chain scores well against it, that is a genuine (if synthetic) test of the
recursion, not a tautology.

Everything produced here is fabricated. It carries season labels like
``2023-24S`` and player names like ``BOS Guard 1`` precisely so it can never
be mistaken for real NBA data.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from app.ingest.schema import (
    GameRecord,
    PlayerBoxRecord,
    PlayRecord,
    format_clock,
    seconds_remaining,
)
from app.ingest.teams_static import TEAMS

PERIOD_SECONDS = 12 * 60
OT_SECONDS = 5 * 60
HOME_ADVANTAGE_PPP = 0.055  # applied to the home offense; nets ~+2.5 points/game


@dataclass
class TeamStrength:
    team_id: int
    abbreviation: str
    off_ppp: float  # points per possession
    def_ppp: float  # points per possession allowed
    pace: float  # possessions per 48 minutes
    three_rate: float


def build_league(
    rng: random.Random, three_rate_shift: float = 0.0, ppp_shift: float = 0.0
) -> dict[int, TeamStrength]:
    """Draw a 30-team league.

    ``three_rate_shift`` and ``ppp_shift`` let successive synthetic seasons
    drift, so the league-trends endpoints have an actual trend to find rather
    than 30 years of flat noise.
    """
    league: dict[int, TeamStrength] = {}
    base_ppp = 1.145 + ppp_shift
    base_three = 0.395 + three_rate_shift
    for t in TEAMS:
        league[t.id] = TeamStrength(
            team_id=t.id,
            abbreviation=t.abbreviation,
            off_ppp=rng.gauss(base_ppp, 0.030),
            def_ppp=rng.gauss(base_ppp, 0.028),
            pace=rng.gauss(99.5, 2.6),
            three_rate=min(0.60, max(0.25, rng.gauss(base_three, 0.045))),
        )
    return league


def _roster(abbrev: str) -> list[str]:
    slots = ["Guard 1", "Guard 2", "Wing 1", "Wing 2", "Big 1", "Guard 3", "Wing 3", "Big 2"]
    return [f"{abbrev} {s}" for s in slots]


@dataclass
class _Possession:
    points: int
    event_type: str
    is_three: bool
    shot_distance: float | None
    fga: int
    fg3a: int
    fg3m: int
    fta: int
    oreb: int
    tov: int
    description: str
    player: str


def _simulate_possession(
    rng: random.Random,
    off: TeamStrength,
    deff: TeamStrength,
    players: list[str],
    env: float = 1.0,
) -> _Possession:
    """One possession. Returns points plus the box-score deltas it generated.

    ``env`` is a game-level scoring-environment multiplier (officiating, rest,
    altitude, whether the threes are falling). It moves both teams together,
    so it widens the distribution of game *totals* without widening margins --
    which is the right shape, since real totals vary more than margins do.
    """
    player = rng.choice(players)
    # Efficiency is the offense's rate pulled toward the defense's.
    ppp = 0.5 * (off.off_ppp + deff.def_ppp)
    scale = (ppp / 1.145) * env

    r = rng.random()
    if r < 0.126:  # live-ball turnover
        return _Possession(0, "TURNOVER", False, None, 0, 0, 0, 0, 0, 1,
                           f"{player} Turnover", player)
    if r < 0.126 + 0.115 * scale:  # shooting foul -> two free throws
        made = sum(1 for _ in range(2) if rng.random() < 0.785)
        return _Possession(made, "FREE_THROW", False, None, 0, 0, 0, 2, 0, 0,
                           f"{player} Free Throw {made} of 2", player)

    is_three = rng.random() < off.three_rate
    if is_three:
        dist = rng.uniform(23.0, 27.0)
        if rng.random() < 0.366 * scale:
            return _Possession(3, "SHOT", True, dist, 1, 1, 1, 0, 0, 0,
                               f"{player} 3PT Jump Shot ({int(dist)}')", player)
        oreb = 1 if rng.random() < 0.26 else 0
        return _Possession(0, "MISS", True, dist, 1, 1, 0, 0, oreb, 0,
                           f"MISS {player} 3PT Jump Shot ({int(dist)}')", player)

    # Shot-location mix: rim / mid / long two, with realistic conversion rates.
    zone = rng.random()
    if zone < 0.52:
        dist, base, shot = rng.uniform(0, 4), 0.665, "Layup"
    elif zone < 0.80:
        dist, base, shot = rng.uniform(4, 14), 0.455, "Floating Jump Shot"
    else:
        dist, base, shot = rng.uniform(14, 22), 0.435, "Jump Shot"

    if rng.random() < base * scale:
        return _Possession(2, "SHOT", False, dist, 1, 0, 0, 0, 0, 0,
                           f"{player} {shot} ({int(dist)}')", player)
    oreb = 1 if rng.random() < 0.25 else 0
    return _Possession(0, "MISS", False, dist, 1, 0, 0, 0, oreb, 0,
                       f"MISS {player} {shot} ({int(dist)}')", player)


def simulate_game(
    game_id: str,
    season: str,
    game_date: str,
    home: TeamStrength,
    away: TeamStrength,
    rng: random.Random,
    season_type: str = "Regular Season",
) -> GameRecord:
    home_players = _roster(home.abbreviation)
    away_players = _roster(away.abbreviation)

    record = GameRecord(
        id=game_id,
        season=season,
        season_type=season_type,
        game_date=game_date,
        home_team_id=home.team_id,
        away_team_id=away.team_id,
        home_score=0,
        away_score=0,
        periods=4,
    )

    box: dict[str, dict[str, float]] = {}

    def bump(player: str, team_id: int, **deltas):
        row = box.setdefault(
            player,
            {"team_id": team_id, "points": 0, "rebounds": 0, "assists": 0,
             "fg3a": 0, "fg3m": 0, "minutes": 0.0},
        )
        for k, v in deltas.items():
            row[k] += v

    home_score = away_score = 0
    event_num = 0
    home_boosted = TeamStrength(
        team_id=home.team_id,
        abbreviation=home.abbreviation,
        off_ppp=home.off_ppp + HOME_ADVANTAGE_PPP,
        def_ppp=home.def_ppp,
        pace=home.pace,
        three_rate=home.three_rate,
    )
    avg_pace = 0.5 * (home.pace + away.pace)
    seconds_per_poss = (48 * 60) / (2 * avg_pace)
    env = rng.gauss(1.0, 0.035)  # game-level scoring environment

    def run_period(period: int, length: int, offense_home: bool) -> bool:
        """Play one period. Returns which team ends with the ball (unused)."""
        nonlocal home_score, away_score, event_num
        clock = float(length)
        while clock > 0:
            # Home court shows up as a small per-possession efficiency edge.
            off, deff = (home_boosted, away) if offense_home else (away, home)
            players = home_players if offense_home else away_players

            # Garbage time: once a game is out of reach the starters sit and
            # scoring converges. Without this a possession-independent
            # simulator produces far too many 30-point finals.
            margin = home_score - away_score
            lead = margin if offense_home else -margin
            secs_left = seconds_remaining(period, clock)
            garbage = 1.0
            if secs_left < 600 and abs(lead) > 16:
                garbage = 0.93 if lead > 0 else 1.05

            outcome = _simulate_possession(rng, off, deff, players, env * garbage)

            if offense_home:
                home_score += outcome.points
            else:
                away_score += outcome.points

            # A putback after an offensive rebound is a few seconds, not a
            # fresh trip down the floor -- getting this wrong is what makes
            # naive simulators produce 180-point games.
            if outcome.oreb:
                elapsed = max(1.0, rng.gauss(4.0, 1.5))
            else:
                elapsed = max(2.0, rng.gauss(seconds_per_poss, 5.0))
            clock = max(0.0, clock - elapsed)
            event_num += 1
            team_id = home.team_id if offense_home else away.team_id

            record.plays.append(
                PlayRecord(
                    event_num=event_num,
                    period=period,
                    clock=format_clock(clock),
                    seconds_remaining=seconds_remaining(period, clock),
                    event_type=outcome.event_type,
                    description=outcome.description,
                    team_id=team_id,
                    player_name=outcome.player,
                    home_score=home_score,
                    away_score=away_score,
                    score_margin=home_score - away_score,
                    points=outcome.points,
                    shot_distance=(
                        round(outcome.shot_distance, 1) if outcome.shot_distance else None
                    ),
                    is_three=outcome.is_three,
                )
            )

            bump(
                outcome.player,
                team_id,
                points=outcome.points,
                fg3a=outcome.fg3a,
                fg3m=outcome.fg3m,
                minutes=elapsed / 60.0,
            )

            prefix = "home" if offense_home else "away"
            setattr(record, f"{prefix}_fga", getattr(record, f"{prefix}_fga") + outcome.fga)
            setattr(record, f"{prefix}_fg3a", getattr(record, f"{prefix}_fg3a") + outcome.fg3a)
            setattr(record, f"{prefix}_fg3m", getattr(record, f"{prefix}_fg3m") + outcome.fg3m)
            setattr(record, f"{prefix}_fta", getattr(record, f"{prefix}_fta") + outcome.fta)
            setattr(record, f"{prefix}_oreb", getattr(record, f"{prefix}_oreb") + outcome.oreb)
            setattr(record, f"{prefix}_tov", getattr(record, f"{prefix}_tov") + outcome.tov)

            if outcome.oreb:
                bump(outcome.player, team_id, rebounds=1)
            else:
                other = away_players if offense_home else home_players
                bump(
                    rng.choice(other),
                    away.team_id if offense_home else home.team_id,
                    rebounds=1 if outcome.event_type == "MISS" else 0,
                )
                offense_home = not offense_home

        event_num += 1
        record.plays.append(
            PlayRecord(
                event_num=event_num,
                period=period,
                clock="0:00",
                seconds_remaining=seconds_remaining(period, 0),
                event_type="PERIOD_END",
                description=f"End of Period {period}",
                team_id=None,
                player_name=None,
                home_score=home_score,
                away_score=away_score,
                score_margin=home_score - away_score,
            )
        )
        return offense_home

    offense_home = rng.random() < 0.5
    for period in range(1, 5):
        offense_home = run_period(period, PERIOD_SECONDS, offense_home)

    period = 4
    while home_score == away_score:
        period += 1
        record.periods = period
        offense_home = run_period(period, OT_SECONDS, rng.random() < 0.5)

    record.home_score = home_score
    record.away_score = away_score
    record.player_box = [
        PlayerBoxRecord(
            team_id=int(v["team_id"]),
            player_name=name,
            minutes=round(v["minutes"], 1),
            points=int(v["points"]),
            rebounds=int(v["rebounds"]),
            assists=int(v["points"] // 4),
            fg3a=int(v["fg3a"]),
            fg3m=int(v["fg3m"]),
        )
        for name, v in box.items()
    ]
    return record


def simulate_season(
    season: str,
    n_games: int = 200,
    seed: int = 7,
    start_date: str = "2023-10-24",
    three_rate_shift: float = 0.0,
    ppp_shift: float = 0.0,
    league_seed: int | None = None,
) -> list[GameRecord]:
    """Generate ``n_games`` matchups sampled from the 30-team league.

    ``league_seed`` draws the team-strength table independently of the
    game-level randomness. Holding it fixed across seasons means the only
    thing that moves season to season is the requested drift, instead of a
    fresh set of 30 teams swamping it.
    """
    from datetime import date, timedelta

    league = build_league(
        random.Random(seed if league_seed is None else league_seed),
        three_rate_shift,
        ppp_shift,
    )
    rng = random.Random(seed)
    ids = list(league)
    d0 = date.fromisoformat(start_date)

    games: list[GameRecord] = []
    for i in range(n_games):
        home_id, away_id = rng.sample(ids, 2)
        game_date = (d0 + timedelta(days=i // 6)).isoformat()
        games.append(
            simulate_game(
                game_id=f"9{season[:4]}{i:05d}",
                season=season,
                game_date=game_date,
                home=league[home_id],
                away=league[away_id],
                rng=rng,
            )
        )
    return games
