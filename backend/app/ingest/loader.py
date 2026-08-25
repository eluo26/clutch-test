"""Write :class:`GameRecord` objects into the database (idempotently)."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ingest.schema import GameRecord, TeamRecord
from app.models import Game, Play, PlayerBox, Team

log = logging.getLogger(__name__)


def upsert_teams(session: Session, teams: Iterable[TeamRecord]) -> int:
    existing = {t.id for t in session.execute(select(Team)).scalars()}
    added = 0
    for t in teams:
        if t.id in existing:
            continue
        session.add(
            Team(
                id=t.id,
                abbreviation=t.abbreviation,
                full_name=t.full_name,
                conference=t.conference,
            )
        )
        added += 1
    session.commit()
    return added


def upsert_game(session: Session, record: GameRecord) -> None:
    """Replace the game and all its child rows. Safe to re-run."""
    session.execute(delete(Play).where(Play.game_id == record.id))
    session.execute(delete(PlayerBox).where(PlayerBox.game_id == record.id))
    existing = session.get(Game, record.id)
    if existing is not None:
        session.delete(existing)
        session.flush()

    session.add(
        Game(
            id=record.id,
            season=record.season,
            season_type=record.season_type,
            game_date=record.game_date,
            home_team_id=record.home_team_id,
            away_team_id=record.away_team_id,
            home_score=record.home_score,
            away_score=record.away_score,
            periods=record.periods,
            home_fga=record.home_fga,
            home_fg3a=record.home_fg3a,
            home_fg3m=record.home_fg3m,
            home_fta=record.home_fta,
            home_oreb=record.home_oreb,
            home_tov=record.home_tov,
            away_fga=record.away_fga,
            away_fg3a=record.away_fg3a,
            away_fg3m=record.away_fg3m,
            away_fta=record.away_fta,
            away_oreb=record.away_oreb,
            away_tov=record.away_tov,
        )
    )
    session.flush()

    session.add_all(
        Play(
            game_id=record.id,
            event_num=p.event_num,
            period=p.period,
            clock=p.clock,
            seconds_remaining=p.seconds_remaining,
            event_type=p.event_type,
            description=p.description,
            team_id=p.team_id,
            player_name=p.player_name,
            home_score=p.home_score,
            away_score=p.away_score,
            score_margin=p.score_margin,
            points=p.points,
            shot_distance=p.shot_distance,
            is_three=p.is_three,
        )
        for p in record.plays
    )
    session.add_all(
        PlayerBox(
            game_id=record.id,
            team_id=b.team_id,
            player_name=b.player_name,
            minutes=b.minutes,
            points=b.points,
            rebounds=b.rebounds,
            assists=b.assists,
            fg3a=b.fg3a,
            fg3m=b.fg3m,
        )
        for b in record.player_box
    )
    session.commit()


def load_games(session: Session, records: Iterable[GameRecord]) -> int:
    n = 0
    for record in records:
        upsert_game(session, record)
        n += 1
        if n % 25 == 0:
            log.info("loaded %d games", n)
    return n


# --- JSON fixtures ---------------------------------------------------------
# Play-by-play is verbose -- a season of it is tens of megabytes of very
# repetitive JSON. Fixtures are gzipped so the sample data stays small enough
# to live in git without a LFS pointer.
def write_fixture(records: Iterable[GameRecord], path: Path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    games = [r.to_json() for r in records]
    blob = json.dumps(games, separators=(",", ":")).encode("utf-8")
    if path.suffix == ".gz":
        import gzip

        path.write_bytes(gzip.compress(blob, compresslevel=9))
    else:
        path.write_bytes(blob)
    return len(games)


def read_fixture(path: Path) -> list[GameRecord]:
    path = Path(path)
    if path.suffix == ".gz":
        import gzip

        blob = gzip.decompress(path.read_bytes())
    else:
        blob = path.read_bytes()
    return [GameRecord.from_json(d) for d in json.loads(blob)]
