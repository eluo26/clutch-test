"""Brownian-motion-with-drift win probability.

Following Stern (1994), *A Brownian Motion Model for the Progress of Sports
Scores* (JASA 89:427). Let ``X(t)`` be the home team's lead at time ``t``,
where ``t`` runs from 0 at tip-off to 1 at the final buzzer. The model treats
the lead as a Brownian motion with drift ``mu`` and per-game variance
``sigma^2``::

    X(1) - X(t) ~ Normal(mu * (1 - t), sigma^2 * (1 - t))

so the home team's win probability given a current lead ``d`` is

    P(home win) = Phi( (d + mu * s) / (sigma * sqrt(s)) ),    s = 1 - t

``mu`` is the expected full-game margin (home-court advantage, roughly +2 to
+3 in the modern league) and ``sigma`` is the standard deviation of the final
margin (roughly 13-15). Both are estimated from data by
:func:`fit_brownian_params` rather than hard-coded.

Two refinements over the textbook form:

* **Ties go to overtime.** Scores are integers, so the naive ``P(X(1) > 0)``
  quietly assigns the whole probability of an exact tie to the away team. The
  honest statement is

      P(home win) = P(X(1) >= 1) + 0.5 * P(X(1) == 0)

  which, with a half-point continuity correction on a normal approximation,
  collapses to the average of two half-point-shifted normal CDFs. That form is
  exactly symmetric under a sign flip when the drift is zero, which the naive
  version is not.

* **Possession value.** Holding the ball late is worth real equity. We add
  ``possession_value`` points to the effective lead for whichever team has the
  ball, faded out as ``sqrt(s)`` grows so it dominates at the buzzer and
  washes out early.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.winprob.clock import REGULATION_SECONDS, resolve


def _phi(z: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


@dataclass(frozen=True)
class BrownianParams:
    """Fitted parameters of the Brownian model."""

    mu: float = 2.6
    sigma: float = 13.5
    possession_value: float = 0.55
    n_games: int = 0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "mu": self.mu,
            "sigma": self.sigma,
            "possession_value": self.possession_value,
            "n_games": self.n_games,
        }


DEFAULT_PARAMS = BrownianParams()


def win_probability(
    margin: int,
    seconds_remaining: float,
    params: BrownianParams = DEFAULT_PARAMS,
    home_has_ball: bool | None = None,
) -> float:
    """Home win probability.

    Args:
        margin: home score minus away score, right now.
        seconds_remaining: seconds left in regulation, going negative once
            overtime starts. See :mod:`app.winprob.clock` for how overtime and
            the end of the game are told apart.
        params: fitted model parameters.
        home_has_ball: who is in possession, or ``None`` if unknown.
    """
    state = resolve(margin, seconds_remaining)
    if state.is_over:
        return 1.0 if margin > 0 else 0.0

    # Time left as a fraction of a full game, so drift and variance scale
    # correctly: a five-minute overtime carries 300/2880 of a game's worth of
    # both. Home-court drift is dropped in overtime -- the edge is already
    # spent by the time a game gets there.
    s = state.seconds_left / REGULATION_SECONDS
    sqrt_s = math.sqrt(s)
    mu = 0.0 if state.is_overtime else params.mu

    # Expected final margin from here, and its standard deviation.
    expected = float(margin) + mu * s
    if home_has_ball is not None:
        edge = params.possession_value * (1.0 if home_has_ball else -1.0)
        expected += edge * (1.0 - 0.75 * sqrt_s)
    scale = params.sigma * sqrt_s

    # P(margin >= 1) + 0.5 * P(margin == 0), continuity-corrected.
    p = 0.5 * (_phi((expected - 0.5) / scale) + _phi((expected + 0.5) / scale))
    return min(1.0 - 1e-9, max(1e-9, p))


def fit_brownian_params(
    final_margins: Sequence[float],
    possession_value: float = DEFAULT_PARAMS.possession_value,
) -> BrownianParams:
    """Maximum-likelihood fit of ``mu`` and ``sigma``.

    Under the model the final margin ``X(1)`` is ``Normal(mu, sigma^2)``, so
    the MLE is just the sample mean and (biased-corrected) standard deviation
    of observed final margins. Estimating from the endpoint alone is exactly
    right here: the Brownian bridge structure means intermediate scores carry
    no extra information about ``mu`` or ``sigma``.
    """
    margins = [float(m) for m in final_margins]
    n = len(margins)
    if n < 2:
        return DEFAULT_PARAMS
    mu = sum(margins) / n
    var = sum((m - mu) ** 2 for m in margins) / (n - 1)
    sigma = math.sqrt(var) if var > 0 else DEFAULT_PARAMS.sigma
    return BrownianParams(
        mu=mu, sigma=sigma, possession_value=possession_value, n_games=n
    )


def win_probability_path(
    events: Iterable[tuple[int, float, bool | None]],
    params: BrownianParams = DEFAULT_PARAMS,
) -> list[float]:
    """Vectorised-ish convenience: map ``(margin, secs_left, has_ball)`` to WP."""
    return [win_probability(m, s, params, b) for m, s, b in events]


def leverage(
    margin: int,
    seconds_remaining: float,
    params: BrownianParams = DEFAULT_PARAMS,
) -> float:
    """How much a single possession swings the game, in win-probability points.

    Defined as the spread between the WP after a made three and the WP after
    an empty possession -- a cheap, interpretable "how clutch is this moment"
    number for the UI.
    """
    made = win_probability(margin + 3, seconds_remaining, params)
    miss = win_probability(margin, seconds_remaining, params)
    return abs(made - miss)
