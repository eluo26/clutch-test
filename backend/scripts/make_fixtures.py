#!/usr/bin/env python3
"""Regenerate the bundled sample fixtures in ``backend/data/sample/``.

Deterministic: fixed seeds in, identical bytes out. Run from ``backend/``::

    python scripts/make_fixtures.py

The three synthetic seasons drift in three-point rate and efficiency so the
league-trends and projection endpoints have a real trend to fit.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingest import loader, synthetic  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "sample"

# Held constant across seasons so the only thing that drifts is the drift.
LEAGUE_SEED = 4242

SEASONS = [
    # season,      start date,   games, seed, 3PAr shift, PPP shift
    ("2021-22S", "2021-10-19", 30, 1021, -0.045, -0.020),
    ("2022-23S", "2022-10-18", 30, 2022, -0.022, -0.008),
    ("2023-24S", "2023-10-24", 40, 3023, 0.000, 0.000),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.json*"):
        old.unlink()

    total = 0
    for season, start, n, seed, tshift, pshift in SEASONS:
        games = synthetic.simulate_season(
            season,
            n_games=n,
            seed=seed,
            start_date=start,
            three_rate_shift=tshift,
            ppp_shift=pshift,
            league_seed=LEAGUE_SEED,
        )
        path = OUT / f"season_{season}.json.gz"
        loader.write_fixture(games, path)
        total += len(games)

        rate = sum(g.home_fg3a + g.away_fg3a for g in games) / sum(
            g.home_fga + g.away_fga for g in games
        )
        avg_total = sum(g.home_score + g.away_score for g in games) / len(games)
        print(
            f"{season}: {len(games):3d} games  3PAr {rate:.3f}  "
            f"avg total {avg_total:.1f}  {path.stat().st_size / 1e6:.2f} MB"
        )

    print(f"\n{total} games written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
