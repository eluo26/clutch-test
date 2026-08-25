"""Turning a clock reading into "how much basketball is left".

Both models need the same answer to one question: given ``seconds_remaining``
(counting down through regulation and going negative in overtime, see
``app/ingest/schema.py``), how much time is left to play, and is the game over?

Regulation is easy. Overtime is where a naive implementation goes wrong, and
visibly so: treating ``seconds_remaining <= 0`` as "finished" makes win
probability snap to 100% the instant a team leads in overtime, which is both
absurd and very obvious on a chart.

The subtlety is that a boundary value is ambiguous. ``seconds_remaining == 0``
is simultaneously "the final buzzer of regulation" and "the tip of the first
overtime"; ``-300`` is both the end of OT1 and the start of OT2. The
disambiguator is the score: **an overtime period only ever begins from a tie.**
So at a boundary, a non-zero margin means the game is over, and a zero margin
means another five minutes are about to be played.
"""

from __future__ import annotations

from typing import NamedTuple

REGULATION_SECONDS = 48 * 60
OVERTIME_SECONDS = 5 * 60


class ClockState(NamedTuple):
    seconds_left: float
    """Seconds of play remaining in the current period of play (regulation as a
    whole, or the current overtime). Zero when the game is over."""

    is_over: bool
    """True when no basketball remains; the caller resolves 1/0 by margin."""

    is_overtime: bool

    period_length: float
    """Length of the period being played, for scaling drift and variance."""


def resolve(margin: int, seconds_remaining: float) -> ClockState:
    """Classify a clock reading. See the module docstring for the boundary rule."""
    if seconds_remaining > 0:
        return ClockState(
            seconds_left=min(seconds_remaining, REGULATION_SECONDS),
            is_over=False,
            is_overtime=False,
            period_length=REGULATION_SECONDS,
        )

    elapsed_in_overtime = (-seconds_remaining) % OVERTIME_SECONDS
    at_boundary = elapsed_in_overtime == 0

    if at_boundary and margin != 0:
        # A period ended with somebody ahead. That is the end of the game.
        return ClockState(0.0, True, seconds_remaining < 0, OVERTIME_SECONDS)

    return ClockState(
        seconds_left=OVERTIME_SECONDS - elapsed_in_overtime,
        is_over=False,
        is_overtime=True,
        period_length=OVERTIME_SECONDS,
    )
