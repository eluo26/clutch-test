"""Properties both win-probability models must satisfy.

These are written as invariants rather than golden numbers on purpose: a
golden number breaks the moment anyone retunes a parameter, whereas "a bigger
lead is never worse" catches the sign errors and off-by-ones that actually
happen.
"""

from __future__ import annotations

import math

import pytest

from app.winprob import markov
from app.winprob.brownian import (
    REGULATION_SECONDS,
    BrownianParams,
    fit_brownian_params,
    leverage,
)
from app.winprob.brownian import (
    win_probability as bwp,
)


# --- Brownian --------------------------------------------------------------
class TestBrownian:
    def test_tipoff_is_near_even_with_home_edge(self):
        p = bwp(0, REGULATION_SECONDS)
        assert 0.5 < p < 0.62, p

    def test_buzzer_is_decisive(self):
        assert bwp(1, 0) == 1.0
        assert bwp(-1, 0) == 0.0
        assert bwp(0, 0) == pytest.approx(0.5, abs=0.05)

    def test_monotone_in_margin(self):
        for secs in (2880, 1440, 600, 120, 10):
            probs = [bwp(d, secs) for d in range(-25, 26)]
            assert probs == sorted(probs), f"not monotone at {secs}s"

    def test_lead_is_safer_as_the_clock_runs_down(self):
        assert bwp(8, 60) > bwp(8, 600) > bwp(8, 2400)

    def test_a_deficit_gets_worse_as_the_clock_runs_down(self):
        assert bwp(-8, 60) < bwp(-8, 600) < bwp(-8, 2400)

    def test_symmetry_with_zero_drift(self):
        params = BrownianParams(mu=0.0, sigma=14.0, possession_value=0.0)
        for d in range(1, 20):
            for secs in (2400, 900, 200):
                assert bwp(d, secs, params) == pytest.approx(
                    1.0 - bwp(-d, secs, params), abs=1e-9
                )

    def test_possession_helps_the_team_holding_it(self):
        with_ball = bwp(0, 20, home_has_ball=True)
        without = bwp(0, 20, home_has_ball=False)
        assert with_ball > without

    def test_fit_recovers_known_parameters(self):
        # Sample from a known normal; the MLE should find it back.
        import random

        rng = random.Random(0)
        margins = [rng.gauss(3.0, 14.0) for _ in range(20000)]
        params = fit_brownian_params(margins)
        assert params.mu == pytest.approx(3.0, abs=0.25)
        assert params.sigma == pytest.approx(14.0, abs=0.25)
        assert params.n_games == 20000

    def test_fit_falls_back_when_there_is_no_data(self):
        assert fit_brownian_params([]).n_games == 0
        assert fit_brownian_params([5.0]).n_games == 0

    def test_leverage_peaks_in_close_late_games(self):
        close_late = leverage(0, 30)
        blowout_late = leverage(28, 30)
        close_early = leverage(0, 2400)
        assert close_late > close_early
        assert close_late > blowout_late

    def test_never_returns_exactly_zero_or_one_mid_game(self):
        # Log loss is undefined at the endpoints; the model must not go there
        # while the game is still live.
        for d in (-60, -30, 0, 30, 60):
            p = bwp(d, 1)
            assert 0.0 < p < 1.0


# --- Markov ----------------------------------------------------------------
class TestMarkov:
    solver = markov.MarkovSolver()

    def test_default_model_is_league_average(self):
        ppp = markov.DEFAULT_POSSESSION_MODEL.points_per_possession
        assert 1.08 < ppp < 1.20, ppp

    def test_outcome_probabilities_sum_to_one(self):
        total = sum(p for _, p in markov.DEFAULT_POSSESSION_MODEL.outcomes)
        assert total == pytest.approx(1.0, abs=1e-12)

    def test_buzzer_is_decisive(self):
        assert self.solver.win_probability(3, 0, True) == pytest.approx(1.0, abs=1e-8)
        assert self.solver.win_probability(-3, 0, True) == pytest.approx(0.0, abs=1e-8)
        assert self.solver.win_probability(0, 0, True) == pytest.approx(0.5, abs=1e-8)

    def test_monotone_in_margin(self):
        for k in (1, 5, 20, 100):
            probs = [self.solver.win_probability(d, k, True) for d in range(-20, 21)]
            assert probs == sorted(probs), f"not monotone at k={k}"

    def test_sign_flip_symmetry(self):
        for k in range(1, 30):
            for d in range(1, 12):
                assert self.solver.win_probability(d, k, True) == pytest.approx(
                    1.0 - self.solver.win_probability(-d, k, False), abs=1e-9
                )

    def test_last_possession_advantage_is_large_when_tied(self):
        # Tied with one possession left, having the ball is close to decisive.
        edge = self.solver.win_probability(0, 1, True) - self.solver.win_probability(
            0, 1, False
        )
        assert edge > 0.4, edge

    def test_possession_edge_decays_with_time(self):
        late = self.solver.win_probability(0, 1, True) - self.solver.win_probability(
            0, 1, False
        )
        early = self.solver.win_probability(0, 101, True) - self.solver.win_probability(
            0, 101, False
        )
        assert late > early
        assert early < 0.10

    def test_three_point_deficit_with_the_ball_beats_four(self):
        # The classic endgame asymmetry: down 3 you have a shot, down 4 you do not.
        down_three = self.solver.win_probability(-3, 1, True)
        down_four = self.solver.win_probability(-4, 1, True)
        assert down_three > down_four
        assert down_four == pytest.approx(0.0, abs=1e-9)

    def test_offensive_rebounding_helps_the_offense(self):
        no_oreb = markov.MarkovSolver(
            markov.PossessionModel(oreb_prob=0.0), max_possessions=40
        )
        with_oreb = markov.MarkovSolver(
            markov.PossessionModel(oreb_prob=0.30), max_possessions=40
        )
        assert with_oreb.win_probability(-2, 1, True) >= no_oreb.win_probability(
            -2, 1, True
        )

    def test_time_left_to_trip_conversion(self):
        assert markov.trips_remaining(0) == 0
        assert markov.trips_remaining(-5) == 0
        assert markov.trips_remaining(1) == 1
        assert markov.trips_remaining(2880) == pytest.approx(220, abs=2)

    def test_raw_clock_conversion_understands_overtime(self):
        # Zero on the regulation clock is the tip of overtime, not the end of
        # the game -- see app/winprob/clock.py.
        assert markov.possessions_remaining(2880) == pytest.approx(220, abs=2)
        assert markov.possessions_remaining(0) == pytest.approx(23, abs=2)

    def test_margin_cap_saturates_rather_than_crashing(self):
        assert self.solver.win_probability(500, 50, True) == pytest.approx(1.0, abs=1e-6)
        assert self.solver.win_probability(-500, 50, True) == pytest.approx(
            0.0, abs=1e-6
        )


# --- the two models against each other -------------------------------------
def test_models_broadly_agree_in_the_middle_of_a_game():
    """Two independent derivations should not disagree wildly.

    They will not match exactly -- one is a diffusion approximation and the
    other is a discrete chain, which is the entire point of having both. But a
    gap of more than ~12 points of win probability at a normal game state
    means one of them is wrong.
    """
    params = BrownianParams(mu=2.6, sigma=14.0)
    for secs in (1800, 900, 400):
        for d in (-10, -5, 0, 5, 10):
            b = bwp(d, secs, params)
            m = markov.win_probability(d, secs, True)
            assert abs(b - m) < 0.12, f"d={d} secs={secs}: {b:.3f} vs {m:.3f}"


def test_blend_sits_between_its_components():
    from app.winprob.service import score_state

    params = BrownianParams(mu=2.6, sigma=14.0)
    for secs in (300, 120, 45):
        for d in (-6, -2, 0, 2, 6):
            b = bwp(d, secs, params, True)
            m = markov.win_probability(d, secs, True)
            blend = score_state(d, secs, "blend", params, True)
            assert min(b, m) - 1e-9 <= blend <= max(b, m) + 1e-9


def test_all_probabilities_are_finite():
    for secs in (0, 1, 60, 720, 2880):
        for d in range(-40, 41, 5):
            for p in (bwp(d, secs), markov.win_probability(d, secs, True)):
                assert math.isfinite(p) and 0.0 <= p <= 1.0
