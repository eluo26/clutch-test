"""Ingest CLI.

    python -m app.ingest.cli seed                 # load bundled sample data
    python -m app.ingest.cli generate --season 2023-24S --games 400
    python -m app.ingest.cli nba --season 2023-24 --limit 50
    python -m app.ingest.cli backtest --model blend
    python -m app.ingest.cli stats
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.config import BACKEND_ROOT
from app.db import SessionLocal, init_db
from app.ingest import loader, synthetic
from app.ingest.teams_static import TEAMS

SAMPLE_DIR = BACKEND_ROOT / "data" / "sample"

log = logging.getLogger("clutch.ingest")


def _session():
    init_db()
    return SessionLocal()


def cmd_seed(args) -> int:
    session = _session()
    try:
        loader.upsert_teams(session, TEAMS)
        files = sorted(SAMPLE_DIR.glob("*.json*"))
        if not files:
            print(f"No fixtures in {SAMPLE_DIR}. Run `generate --write-fixture` first.")
            return 1
        total = 0
        for f in files:
            records = loader.read_fixture(f)
            total += loader.load_games(session, records)
            print(f"  {f.name}: {len(records)} games")
        print(f"Seeded {total} games from bundled sample data.")
        return 0
    finally:
        session.close()


def cmd_generate(args) -> int:
    records = synthetic.simulate_season(
        season=args.season, n_games=args.games, seed=args.seed
    )
    if args.write_fixture:
        path = Path(args.write_fixture)
        n = loader.write_fixture(records, path)
        print(f"Wrote {n} synthetic games to {path}")
        return 0

    session = _session()
    try:
        loader.upsert_teams(session, TEAMS)
        n = loader.load_games(session, records)
        print(f"Loaded {n} synthetic games for season {args.season}.")
        return 0
    finally:
        session.close()


def cmd_nba(args) -> int:
    from app.ingest import nba_source

    try:
        teams = nba_source.fetch_teams()
    except nba_source.NBASourceUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    session = _session()
    try:
        loader.upsert_teams(session, teams)
        print(f"Fetching game list for {args.season}...")
        ids = nba_source.list_game_ids(args.season, args.season_type)
        if args.limit:
            ids = ids[: args.limit]
        print(f"{len(ids)} games to ingest. This is rate-limited; expect ~1s per game.")

        n = 0
        for record in nba_source.fetch_games(ids, args.season, args.season_type):
            loader.upsert_game(session, record)
            n += 1
            print(f"  [{n}/{len(ids)}] {record.id} "
                  f"{record.away_score}-{record.home_score} "
                  f"({len(record.plays)} plays)")
        print(f"Ingested {n} games.")
        return 0
    finally:
        session.close()


def cmd_backtest(args) -> int:
    from app.winprob import service as wp

    session = _session()
    try:
        result = wp.backtest(
            session, model=args.model, season=args.season, stride_seconds=args.stride
        )
        o = result.overall
        print(f"\nModel: {result.model}   games: {result.n_games}   "
              f"forecasts: {result.n_forecasts}")
        print(f"Fitted params: {result.params}")
        print(f"\n  Brier        {o['brier']:.5f}   (base rate {o['base_rate']:.3f})")
        print(f"  Brier skill  {o['brier_skill']:+.4f}")
        print(f"  Log loss     {o['log_loss']:.5f}")
        print(f"  ECE / MCE    {o['ece']:.4f} / {o['mce']:.4f}")

        print("\n  Reliability diagram")
        print("  predicted   observed      n")
        for b in o["bins"]:
            if not b["count"]:
                continue
            bar = "#" * int(b["observed_rate"] * 40)
            print(f"  {b['mean_predicted']:9.3f} {b['observed_rate']:9.3f} "
                  f"{b['count']:6d}  {bar}")

        print("\n  By game state")
        for name, rep in result.by_time.items():
            if not rep["n"]:
                continue
            print(f"  {name:22s} Brier {rep['brier']:.5f}  "
                  f"skill {rep['brier_skill']:+.4f}  n={rep['n']}")
        return 0
    finally:
        session.close()


def cmd_stats(args) -> int:
    from sqlalchemy import func, select

    from app.models import Game, Play, PlayerBox, Team

    session = _session()
    try:
        for label, model in (
            ("teams", Team), ("games", Game), ("plays", Play), ("box rows", PlayerBox)
        ):
            n = session.execute(select(func.count()).select_from(model)).scalar_one()
            print(f"  {label:10s} {n:>8,}")
        seasons = session.execute(
            select(Game.season, func.count(Game.id)).group_by(Game.season)
        ).all()
        print("\n  seasons:")
        for s, n in seasons:
            print(f"    {s}: {n} games")
        return 0
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(prog="clutch-ingest")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("seed", help="load the bundled sample fixtures")
    p.set_defaults(func=cmd_seed)

    p = sub.add_parser("generate", help="simulate synthetic games")
    p.add_argument("--season", default="2023-24S")
    p.add_argument("--games", type=int, default=200)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--write-fixture", help="write JSON instead of loading to the DB")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("nba", help="ingest real games via nba_api")
    p.add_argument("--season", required=True, help="e.g. 2023-24")
    p.add_argument("--season-type", default="Regular Season")
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(func=cmd_nba)

    p = sub.add_parser("backtest", help="calibration backtest")
    p.add_argument("--model", default="blend", choices=["brownian", "markov", "blend"])
    p.add_argument("--season", default=None)
    p.add_argument("--stride", type=int, default=30)
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("stats", help="row counts")
    p.set_defaults(func=cmd_stats)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
