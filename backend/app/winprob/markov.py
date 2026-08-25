"""Markov chain over possession states.

The Brownian model treats scoring as a continuous diffusion. That is a good
approximation in the second quarter and a bad one with 40 seconds left, where
the game is visibly discrete: a fixed number of possessions remain, each worth
0, 1, 2 or 3 points, and *who has the ball* dominates.

This module models the endgame exactly as what it is -- an absorbing Markov
chain on the state

    (k, d, o)   k = possessions remaining
                d = home lead
                o = team in possession (home / away)

with transitions driven by a per-possession points distribution. The chain is
solved by backward induction over ``k``, which is exact (no simulation error)
and runs in ``O(k * |d| * |outcomes|)``.

A note on what ``k`` counts. Each step of the chain is one *trip* -- a single
shot opportunity -- not a possession in the box-score sense. An offensive
rebound consumes a step and leaves the ball with the same team, which is how
second chances enter the model. A game has roughly 200 possessions but closer
to 220 trips, so :data:`SECONDS_PER_TRIP` is 2880 / 220, not 2880 / 200.
Getting this backwards inflates every fitted rate by about 10%.

The same recursion is implemented in the Java service under ``java-sim/``;
:func:`win_probability` here is the reference implementation and the fallback
used whenever that service is not running.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.winprob.clock import resolve

# Score differentials outside this band are decided for all practical
# purposes; clipping keeps the state space small.
MARGIN_CAP = 45

# 2880 regulation seconds over ~220 trips (both teams), where a trip is one
# shot opportunity including second chances.
SECONDS_PER_TRIP = 13.1

# Backwards-compatible alias.
SECONDS_PER_POSSESSION = SECONDS_PER_TRIP


@dataclass(frozen=True)
class PossessionModel:
    """Outcome distribution for a single possession.

    Probabilities are over points scored by the team with the ball. The
    defaults sum to 1.138 points per possession, which is league average; the
    remaining 47% of possessions end in a miss or a turnover. ``oreb_prob`` is
    the chance the offense keeps the ball after a miss, which is what makes
    the chain non-alternating.
    """

    p_three: float = 0.105  # made 3
    p_two: float = 0.275  # made 2
    p_and_one: float = 0.025  # made 2 + 1
    p_two_ft: float = 0.075  # two made free throws
    p_one_ft: float = 0.048  # one made free throw
    oreb_prob: float = 0.135
    overtime_home_win_prob: float = 0.5

    @property
    def p_empty(self) -> float:
        scored = (
            self.p_three
            + self.p_two
            + self.p_and_one
            + self.p_two_ft
            + self.p_one_ft
        )
        return max(0.0, 1.0 - scored)

    @property
    def outcomes(self) -> list[tuple[int, float]]:
        """``(points, probability)`` pairs summing to 1."""
        return [
            (0, self.p_empty),
            (1, self.p_one_ft),
            (2, self.p_two + self.p_two_ft),
            (3, self.p_three + self.p_and_one),
        ]

    @property
    def points_per_possession(self) -> float:
        return sum(pts * p for pts, p in self.outcomes)

    def as_dict(self) -> dict[str, float]:
        return {
            "p_three": self.p_three,
            "p_two": self.p_two,
            "p_and_one": self.p_and_one,
            "p_two_ft": self.p_two_ft,
            "p_one_ft": self.p_one_ft,
            "oreb_prob": self.oreb_prob,
            "points_per_possession": self.points_per_possession,
        }


DEFAULT_POSSESSION_MODEL = PossessionModel()


@dataclass
class _Layer:
    """Win probabilities for every ``(d, o)`` at a fixed ``k``."""

    home_ball: dict[int, float] = field(default_factory=dict)
    away_ball: dict[int, float] = field(default_factory=dict)


def _terminal_value(d: int, model: PossessionModel) -> float:
    if d > 0:
        return 1.0
    if d < 0:
        return 0.0
    return model.overtime_home_win_prob


def trips_remaining(seconds_left: float) -> int:
    """Convert *time left to play* into a count of remaining trips.

    Takes seconds of play remaining, not a raw clock reading -- use
    :func:`app.winprob.clock.resolve` first if you have the latter, so that
    overtime is handled rather than treated as a finished game.
    """
    if seconds_left <= 0:
        return 0
    return max(1, int(round(seconds_left / SECONDS_PER_TRIP)))


def possessions_remaining(seconds_remaining: float) -> int:
    """Trips left given a raw clock reading, overtime included."""
    state = resolve(0, seconds_remaining)
    return 0 if state.is_over else trips_remaining(state.seconds_left)


def solve(
    max_possessions: int,
    model: PossessionModel = DEFAULT_POSSESSION_MODEL,
) -> list[_Layer]:
    """Backward induction. Returns layers indexed by possessions remaining."""
    margins = range(-MARGIN_CAP, MARGIN_CAP + 1)
    outcomes = [(pts, p) for pts, p in model.outcomes if p > 0.0]
    oreb = model.oreb_prob

    layers: list[_Layer] = []
    base = _Layer()
    for d in margins:
        v = _terminal_value(d, model)
        base.home_ball[d] = v
        base.away_ball[d] = v
    layers.append(base)

    for k in range(1, max_possessions + 1):
        prev = layers[k - 1]
        cur = _Layer()
        for d in margins:
            # --- home has the ball ---------------------------------------
            acc = 0.0
            for pts, p in outcomes:
                nd = min(MARGIN_CAP, max(-MARGIN_CAP, d + pts))
                if pts == 0:
                    # A miss can be rebounded by the offense.
                    acc += p * (
                        oreb * prev.home_ball[nd] + (1.0 - oreb) * prev.away_ball[nd]
                    )
                else:
                    acc += p * prev.away_ball[nd]
            cur.home_ball[d] = acc

            # --- away has the ball ---------------------------------------
            acc = 0.0
            for pts, p in outcomes:
                nd = min(MARGIN_CAP, max(-MARGIN_CAP, d - pts))
                if pts == 0:
                    acc += p * (
                        oreb * prev.away_ball[nd] + (1.0 - oreb) * prev.home_ball[nd]
                    )
                else:
                    acc += p * prev.home_ball[nd]
            cur.away_ball[d] = acc

        layers.append(cur)
    return layers


class MarkovSolver:
    """Caches the backward-induction table across calls."""

    def __init__(
        self,
        model: PossessionModel = DEFAULT_POSSESSION_MODEL,
        max_possessions: int = 220,
    ) -> None:
        self.model = model
        self.max_possessions = max_possessions
        self._layers = solve(max_possessions, model)

    def win_probability(
        self,
        margin: int,
        possessions_left: int,
        home_has_ball: bool = True,
    ) -> float:
        k = max(0, min(self.max_possessions, int(possessions_left)))
        d = min(MARGIN_CAP, max(-MARGIN_CAP, int(margin)))
        layer = self._layers[k]
        value = layer.home_ball[d] if home_has_ball else layer.away_ball[d]
        return min(1.0 - 1e-9, max(1e-9, value))

    def win_probability_from_clock(
        self,
        margin: int,
        seconds_remaining: float,
        home_has_ball: bool = True,
    ) -> float:
        """Score a clock reading, handling overtime.

        Once the clock passes zero the chain is solved over the remaining
        overtime trips instead of stopping -- see :mod:`app.winprob.clock`.
        """
        state = resolve(margin, seconds_remaining)
        if state.is_over:
            return 1.0 if margin > 0 else 0.0
        return self.win_probability(
            margin, trips_remaining(state.seconds_left), home_has_ball
        )


_default_solver: MarkovSolver | None = None


def default_solver() -> MarkovSolver:
    global _default_solver
    if _default_solver is None:
        _default_solver = MarkovSolver()
    return _default_solver


def win_probability(
    margin: int,
    seconds_remaining: float,
    home_has_ball: bool = True,
    model: PossessionModel | None = None,
) -> float:
    """Convenience wrapper using the shared cached solver."""
    solver = default_solver() if model is None else MarkovSolver(model)
    return solver.win_probability_from_clock(margin, seconds_remaining, home_has_ball)
