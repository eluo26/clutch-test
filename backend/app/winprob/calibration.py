"""Calibration metrics and reliability-diagram backtesting.

A win-probability model is *calibrated* when, across all the moments it said
"70%", the home team actually won about 70% of the time. Discrimination
(ranking games correctly) and calibration are different things, so we report
both a proper scoring rule and the binned reliability curve the frontend
draws.

Metrics:

* **Brier score** -- mean squared error of the probability forecast,
  ``mean((p - y)^2)``. Lower is better; 0.25 is the score of always saying
  50%.
* **Brier skill score** -- ``1 - BS / BS_reference`` against the base rate,
  so a positive number means the model beats "home teams win 58% of the time".
* **Log loss** -- the other standard proper scoring rule, more punishing of
  confident mistakes.
* **Calibration error (ECE / MCE)** -- weighted mean and worst-case gap
  between predicted and observed frequency across reliability bins.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

EPS = 1e-12


@dataclass
class ReliabilityBin:
    lower: float
    upper: float
    count: int
    mean_predicted: float
    observed_rate: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "lower": round(self.lower, 4),
            "upper": round(self.upper, 4),
            "count": self.count,
            "mean_predicted": round(self.mean_predicted, 4),
            "observed_rate": round(self.observed_rate, 4),
            "gap": round(self.observed_rate - self.mean_predicted, 4),
        }


@dataclass
class CalibrationReport:
    n: int
    base_rate: float
    brier: float
    brier_skill: float
    log_loss: float
    ece: float
    mce: float
    bins: list[ReliabilityBin] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "n": self.n,
            "base_rate": round(self.base_rate, 4),
            "brier": round(self.brier, 5),
            "brier_skill": round(self.brier_skill, 5),
            "log_loss": round(self.log_loss, 5),
            "ece": round(self.ece, 5),
            "mce": round(self.mce, 5),
            "bins": [b.as_dict() for b in self.bins],
        }


def brier_score(probs: Sequence[float], outcomes: Sequence[int]) -> float:
    if not probs:
        return float("nan")
    return sum((p - y) ** 2 for p, y in zip(probs, outcomes, strict=False)) / len(probs)


def log_loss(probs: Sequence[float], outcomes: Sequence[int]) -> float:
    if not probs:
        return float("nan")
    total = 0.0
    for p, y in zip(probs, outcomes, strict=False):
        q = min(1.0 - EPS, max(EPS, p))
        total -= y * math.log(q) + (1 - y) * math.log(1.0 - q)
    return total / len(probs)


def reliability_bins(
    probs: Sequence[float], outcomes: Sequence[int], n_bins: int = 10
) -> list[ReliabilityBin]:
    edges = [i / n_bins for i in range(n_bins + 1)]
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, y in zip(probs, outcomes, strict=False):
        idx = min(n_bins - 1, max(0, int(p * n_bins)))
        buckets[idx].append((p, y))

    out: list[ReliabilityBin] = []
    for i, bucket in enumerate(buckets):
        if not bucket:
            out.append(ReliabilityBin(edges[i], edges[i + 1], 0, 0.0, 0.0))
            continue
        mean_p = sum(p for p, _ in bucket) / len(bucket)
        rate = sum(y for _, y in bucket) / len(bucket)
        out.append(ReliabilityBin(edges[i], edges[i + 1], len(bucket), mean_p, rate))
    return out


def evaluate(
    probs: Sequence[float], outcomes: Sequence[int], n_bins: int = 10
) -> CalibrationReport:
    """Full calibration report for a set of forecast/outcome pairs."""
    n = len(probs)
    if n == 0:
        return CalibrationReport(0, 0.0, float("nan"), float("nan"), float("nan"), 0, 0)

    base = sum(outcomes) / n
    bs = brier_score(probs, outcomes)
    bs_ref = sum((base - y) ** 2 for y in outcomes) / n
    skill = 1.0 - bs / bs_ref if bs_ref > EPS else 0.0

    bins = reliability_bins(probs, outcomes, n_bins)
    ece = 0.0
    mce = 0.0
    for b in bins:
        if b.count == 0:
            continue
        gap = abs(b.observed_rate - b.mean_predicted)
        ece += (b.count / n) * gap
        mce = max(mce, gap)

    return CalibrationReport(
        n=n,
        base_rate=base,
        brier=bs,
        brier_skill=skill,
        log_loss=log_loss(probs, outcomes),
        ece=ece,
        mce=mce,
        bins=bins,
    )


def evaluate_by_time_bucket(
    records: Sequence[tuple[float, int, float]],
    buckets: Sequence[tuple[str, float, float]] | None = None,
) -> dict[str, dict]:
    """Calibration sliced by game state.

    ``records`` are ``(prob, outcome, seconds_remaining)``. Reporting a single
    Brier score across a whole game hides the interesting failure mode: a
    model can look excellent purely because garbage-time forecasts near 0 and
    1 are easy. Slicing by time remaining exposes where it actually earns its
    keep.
    """
    if buckets is None:
        buckets = [
            ("Q1", 36 * 60, 48 * 60),
            ("Q2", 24 * 60, 36 * 60),
            ("Q3", 12 * 60, 24 * 60),
            ("Q4", 5 * 60, 12 * 60),
            ("Clutch (final 5:00)", 0, 5 * 60),
        ]
    out: dict[str, dict] = {}
    for name, lo, hi in buckets:
        probs = [p for p, _, s in records if lo <= s < hi]
        ys = [y for _, y, s in records if lo <= s < hi]
        out[name] = evaluate(probs, ys).as_dict()
    return out
