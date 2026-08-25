"""Overtime handling.

This is the part of the win-probability code most likely to be wrong in a
naive implementation: treating ``seconds_remaining <= 0`` as "game over" makes
the curve snap to 100% the moment anyone leads in overtime. These tests pin
the boundary rule (a period boundary with a non-zero margin ends the game; a
tie starts another five minutes) and then check that both models behave
sensibly on the overtime side of it.
"""

from __future__ import annotations

import pytest

from app.winprob import markov
from app.winprob.brownian import win_probability as bwp
from app.winprob.clock import OVERTIME_SECONDS, REGULATION_SECONDS, resolve
from app.winprob.service import score_state

MODELS = ["brownian", "markov", "blend"]


class TestResolve:
    def test_regulation_passes_through(self):
        s = resolve(0, 1200)
        assert s.seconds_left == 1200
        assert not s.is_over and not s.is_overtime

    def test_regulation_buzzer_with_a_lead_ends_the_game(self):
        assert resolve(5, 0).is_over
        assert resolve(-5, 0).is_over

    def test_regulation_buzzer_tied_starts_overtime(self):
        s = resolve(0, 0)
        assert not s.is_over
        assert s.is_overtime
        assert s.seconds_left == OVERTIME_SECONDS

    def test_mid_overtime(self):
        s = resolve(2, -120)
        assert not s.is_over
        assert s.is_overtime
        assert s.seconds_left == OVERTIME_SECONDS - 120

    def test_end_of_first_overtime_with_a_lead_ends_the_game(self):
        assert resolve(3, -OVERTIME_SECONDS).is_over

    def test_end_of_first_overtime_tied_starts_a_second(self):
        s = resolve(0, -OVERTIME_SECONDS)
        assert not s.is_over
        assert s.seconds_left == OVERTIME_SECONDS

    def test_deep_into_multiple_overtimes(self):
        # 2.5 periods past regulation, still tied: half of OT3 remains.
        s = resolve(0, -(2 * OVERTIME_SECONDS + 150))
        assert not s.is_over
        assert s.seconds_left == OVERTIME_SECONDS - 150

    def test_period_length_scales_for_overtime(self):
        assert resolve(0, 600).period_length == REGULATION_SECONDS
        assert resolve(0, -60).period_length == OVERTIME_SECONDS


@pytest.mark.parametrize("model", MODELS)
class TestModelsInOvertime:
    def test_tied_at_the_start_of_overtime_is_a_coin_flip(self, model):
        p = score_state(0, 0, model)
        assert 0.4 < p < 0.6, p

    def test_leading_in_overtime_is_not_a_certainty(self, model):
        """The bug this whole module exists for."""
        p = score_state(2, -60, model)  # up 2, four minutes of OT left
        assert 0.5 < p < 0.92, p

    def test_a_lead_in_overtime_still_beats_a_deficit(self, model):
        assert score_state(4, -120, model) > score_state(-4, -120, model)

    def test_overtime_lead_gets_safer_as_that_period_runs_down(self, model):
        early = score_state(3, -30, model)
        late = score_state(3, -270, model)
        assert late > early

    def test_the_game_ending_in_overtime_is_decisive(self, model):
        assert score_state(3, -OVERTIME_SECONDS, model) == 1.0
        assert score_state(-3, -OVERTIME_SECONDS, model) == 0.0

    def test_a_tie_at_the_end_of_an_overtime_resets_to_a_coin_flip(self, model):
        p = score_state(0, -OVERTIME_SECONDS, model)
        assert 0.4 < p < 0.6, p

    def test_second_overtime_behaves_like_the_first(self, model):
        first = score_state(2, -60, model)
        second = score_state(2, -(OVERTIME_SECONDS + 60), model)
        assert first == pytest.approx(second, abs=1e-9)


def test_a_lead_carries_continuously_across_the_buzzer():
    """Up one with a second left is already won; the buzzer changes nothing."""
    assert score_state(1, 1, "blend", home_has_ball=True) > 0.99
    assert score_state(1, 0, "blend", home_has_ball=True) == 1.0


def test_the_last_shot_advantage_vanishes_at_the_buzzer():
    """A genuine discontinuity, and the model should show it.

    Tied with a second left and the ball, you can win outright — that is worth
    a great deal. A moment later the buzzer has gone, the game is tied, and
    overtime resets everyone to even. A model that smooths this over is
    getting the endgame wrong.
    """
    last_shot = score_state(0, 1, "blend", home_has_ball=True)
    buzzer = score_state(0, 0, "blend", home_has_ball=True)
    assert last_shot > 0.65, last_shot
    assert 0.45 < buzzer < 0.60, buzzer


def test_direct_model_entry_points_also_handle_overtime():
    # Callers that skip score_state must not regress.
    assert 0.5 < bwp(2, -60) < 0.95
    assert 0.5 < markov.win_probability(2, -60, True) < 0.95
    assert markov.win_probability(2, -OVERTIME_SECONDS, True) == 1.0


def test_trips_remaining_in_overtime():
    # A five-minute overtime is roughly 23 trips between the two teams.
    assert markov.possessions_remaining(0) == pytest.approx(23, abs=2)
    assert markov.possessions_remaining(-150) == pytest.approx(11, abs=2)
    assert markov.possessions_remaining(-OVERTIME_SECONDS) == pytest.approx(23, abs=2)


def test_a_real_overtime_game_curve_is_not_pinned_to_the_extremes(seeded_db):
    """End to end: no overtime game should show a 100% call before it ends."""
    from sqlalchemy import select

    from app.models import Game
    from app.winprob.service import win_probability_path

    ot_games = (
        seeded_db.execute(select(Game).where(Game.periods > 4)).scalars().all()
    )
    if not ot_games:
        pytest.skip("no overtime games in the sample")

    for game in ot_games:
        points = win_probability_path(seeded_db, game.id, model="blend")
        overtime = [p for p in points if p.seconds_remaining < 0]
        assert overtime, "overtime plays should be scored"

        # With more than a minute of overtime left nothing is decided. (Inside
        # the final minute a two-possession lead genuinely can be a certainty,
        # so that stretch is excluded rather than asserted on, as is the
        # period-ending event itself.)
        early = [
            p
            for p in overtime
            if not (st := resolve(p.margin, p.seconds_remaining)).is_over
            and st.seconds_left > 60
        ]
        for p in early:
            assert 0.02 < p.win_probability < 0.98, (
                f"{game.id} @ {p.seconds_remaining}s margin {p.margin}: "
                f"{p.win_probability}"
            )
        assert early, "expected some early-overtime plays"
