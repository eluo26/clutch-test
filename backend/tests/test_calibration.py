"""Unit tests for the scoring rules and reliability binning.

Calibration code is easy to get subtly wrong and hard to notice, because a
buggy Brier score still returns a plausible-looking number. These tests pin it
against cases with known answers.
"""

from __future__ import annotations

import math
import random

import pytest

from app.winprob.calibration import (
    brier_score,
    evaluate,
    evaluate_by_time_bucket,
    log_loss,
    reliability_bins,
)


class TestBrier:
    def test_perfect_forecasts_score_zero(self):
        assert brier_score([1.0, 0.0, 1.0], [1, 0, 1]) == 0.0

    def test_maximally_wrong_forecasts_score_one(self):
        assert brier_score([0.0, 1.0], [1, 0]) == 1.0

    def test_always_saying_fifty_percent_scores_a_quarter(self):
        assert brier_score([0.5] * 10, [1, 0] * 5) == pytest.approx(0.25)

    def test_empty_input_is_nan_not_a_crash(self):
        assert math.isnan(brier_score([], []))


class TestLogLoss:
    def test_perfect_forecasts_score_near_zero(self):
        assert log_loss([1.0, 0.0], [1, 0]) < 1e-9

    def test_confidently_wrong_is_heavily_penalised(self):
        assert log_loss([0.0], [1]) > 20

    def test_fifty_fifty_scores_ln_two(self):
        assert log_loss([0.5, 0.5], [1, 0]) == pytest.approx(math.log(2))


class TestReliability:
    def test_bins_partition_the_input(self):
        probs = [i / 100 for i in range(100)]
        outcomes = [1 if p > 0.5 else 0 for p in probs]
        bins = reliability_bins(probs, outcomes, n_bins=10)
        assert len(bins) == 10
        assert sum(b.count for b in bins) == 100

    def test_edge_values_land_in_a_bin(self):
        bins = reliability_bins([0.0, 1.0], [0, 1], n_bins=10)
        assert bins[0].count == 1
        assert bins[-1].count == 1

    def test_a_well_calibrated_forecaster_hugs_the_diagonal(self):
        rng = random.Random(0)
        probs, outcomes = [], []
        for _ in range(40000):
            p = rng.random()
            probs.append(p)
            outcomes.append(1 if rng.random() < p else 0)
        report = evaluate(probs, outcomes, n_bins=10)
        assert report.ece < 0.02, report.ece
        for b in report.bins:
            assert abs(b.observed_rate - b.mean_predicted) < 0.05

    def test_an_overconfident_forecaster_is_caught(self):
        """Push every forecast toward the extremes; ECE must notice."""
        rng = random.Random(1)
        probs, outcomes = [], []
        for _ in range(40000):
            true_p = rng.random()
            outcomes.append(1 if rng.random() < true_p else 0)
            probs.append(min(1.0, max(0.0, (true_p - 0.5) * 2.2 + 0.5)))
        report = evaluate(probs, outcomes, n_bins=10)
        assert report.ece > 0.05, report.ece


class TestEvaluate:
    def test_brier_skill_is_zero_for_the_base_rate(self):
        outcomes = [1] * 60 + [0] * 40
        report = evaluate([0.6] * 100, outcomes)
        assert report.brier_skill == pytest.approx(0.0, abs=1e-9)
        assert report.base_rate == pytest.approx(0.6)

    def test_brier_skill_is_positive_for_a_better_forecaster(self):
        outcomes = [1] * 60 + [0] * 40
        probs = [0.9] * 60 + [0.1] * 40
        assert evaluate(probs, outcomes).brier_skill > 0.5

    def test_brier_skill_is_negative_for_a_worse_forecaster(self):
        outcomes = [1] * 60 + [0] * 40
        probs = [0.1] * 60 + [0.9] * 40
        assert evaluate(probs, outcomes).brier_skill < 0

    def test_empty_report_does_not_crash(self):
        report = evaluate([], [])
        assert report.n == 0

    def test_time_buckets_cover_the_game(self):
        records = [(0.5, 1, float(s)) for s in range(0, 2880, 30)]
        out = evaluate_by_time_bucket(records)
        assert set(out) == {"Q1", "Q2", "Q3", "Q4", "Clutch (final 5:00)"}
        assert sum(r["n"] for r in out.values()) == len(records)


class TestBacktestOnRealData:
    def test_backtest_beats_the_base_rate(self, seeded_db):
        """The whole point of the model: it must add information.

        A win-probability model that cannot beat "home teams win ~57% of the
        time" is not worth shipping, so this asserts positive Brier skill.
        """
        from app.winprob.service import backtest

        result = backtest(seeded_db, model="blend", stride_seconds=60)
        assert result.n_forecasts > 500
        assert result.overall["brier_skill"] > 0.15, result.overall

    def test_calibration_sharpens_as_the_game_progresses(self, seeded_db):
        from app.winprob.service import backtest

        result = backtest(seeded_db, model="blend", stride_seconds=60)
        q1 = result.by_time["Q1"]["brier"]
        clutch = result.by_time["Clutch (final 5:00)"]["brier"]
        assert clutch < q1, (clutch, q1)

    @pytest.mark.parametrize("model", ["brownian", "markov", "blend"])
    def test_every_model_is_roughly_calibrated(self, seeded_db, model):
        from app.winprob.service import backtest

        result = backtest(seeded_db, model=model, stride_seconds=60)
        assert result.overall["ece"] < 0.12, (model, result.overall["ece"])
