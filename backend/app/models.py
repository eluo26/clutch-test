"""Relational schema.

Four analytics tables (`teams`, `games`, `plays`, `player_box`) plus `users`
for authentication. The analytics tables are the only ones the
natural-language query layer is allowed to touch -- see app/nlq/guardrails.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = {"comment": "One row per NBA franchise."}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    abbreviation: Mapped[str] = mapped_column(String(4), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(64))
    conference: Mapped[str | None] = mapped_column(String(4), nullable=True)


class Game(Base):
    __tablename__ = "games"
    __table_args__ = (
        Index("ix_games_season_date", "season", "game_date"),
        {"comment": "One row per game, with final score and pace/efficiency box stats."},
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    season: Mapped[str] = mapped_column(String(8), index=True)
    season_type: Mapped[str] = mapped_column(String(16), default="Regular Season")
    game_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD

    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    home_score: Mapped[int] = mapped_column(Integer)
    away_score: Mapped[int] = mapped_column(Integer)
    periods: Mapped[int] = mapped_column(Integer, default=4)

    # Box-score aggregates used by the league-trends endpoints.
    home_fga: Mapped[int] = mapped_column(Integer, default=0)
    home_fg3a: Mapped[int] = mapped_column(Integer, default=0)
    home_fg3m: Mapped[int] = mapped_column(Integer, default=0)
    home_fta: Mapped[int] = mapped_column(Integer, default=0)
    home_oreb: Mapped[int] = mapped_column(Integer, default=0)
    home_tov: Mapped[int] = mapped_column(Integer, default=0)
    away_fga: Mapped[int] = mapped_column(Integer, default=0)
    away_fg3a: Mapped[int] = mapped_column(Integer, default=0)
    away_fg3m: Mapped[int] = mapped_column(Integer, default=0)
    away_fta: Mapped[int] = mapped_column(Integer, default=0)
    away_oreb: Mapped[int] = mapped_column(Integer, default=0)
    away_tov: Mapped[int] = mapped_column(Integer, default=0)

    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id], lazy="joined")
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id], lazy="joined")
    plays: Mapped[list[Play]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )

    @property
    def home_won(self) -> bool:
        return self.home_score > self.away_score

    @property
    def possessions(self) -> float:
        """Standard possession estimate, averaged over both teams."""
        home = (
            self.home_fga
            + 0.44 * self.home_fta
            - self.home_oreb
            + self.home_tov
        )
        away = (
            self.away_fga
            + 0.44 * self.away_fta
            - self.away_oreb
            + self.away_tov
        )
        return 0.5 * (home + away)


class Play(Base):
    """One play-by-play event.

    `seconds_remaining` is seconds left in *regulation* (negative in OT), which
    is what the win-probability models consume. `score_margin` is home - away
    after the event.
    """

    __tablename__ = "plays"
    __table_args__ = (
        UniqueConstraint("game_id", "event_num", name="uq_play_event"),
        Index("ix_plays_game_clock", "game_id", "seconds_remaining"),
        {"comment": "Play-by-play events, one row per event."},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), index=True)
    event_num: Mapped[int] = mapped_column(Integer)
    period: Mapped[int] = mapped_column(Integer)
    clock: Mapped[str] = mapped_column(String(8))  # MM:SS left in period
    seconds_remaining: Mapped[int] = mapped_column(Integer, index=True)

    event_type: Mapped[str] = mapped_column(String(24), index=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id"), nullable=True, index=True
    )
    player_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    home_score: Mapped[int] = mapped_column(Integer)
    away_score: Mapped[int] = mapped_column(Integer)
    score_margin: Mapped[int] = mapped_column(Integer)
    points: Mapped[int] = mapped_column(Integer, default=0)
    shot_distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_three: Mapped[bool] = mapped_column(Boolean, default=False)

    game: Mapped[Game] = relationship(back_populates="plays")


class PlayerBox(Base):
    __tablename__ = "player_box"
    __table_args__ = (
        UniqueConstraint("game_id", "player_name", name="uq_box_player"),
        {"comment": "Per-player box score line for a game."},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    player_name: Mapped[str] = mapped_column(String(64), index=True)
    minutes: Mapped[float] = mapped_column(Float, default=0.0)
    points: Mapped[int] = mapped_column(Integer, default=0)
    rebounds: Mapped[int] = mapped_column(Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    fg3a: Mapped[int] = mapped_column(Integer, default=0)
    fg3m: Mapped[int] = mapped_column(Integer, default=0)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
