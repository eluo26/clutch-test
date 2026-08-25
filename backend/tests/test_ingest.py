"""Ingest: clock arithmetic, the normalized format, and the simulator."""

from __future__ import annotations

import pytest

from app.ingest import synthetic
from app.ingest.loader import read_fixture, write_fixture
from app.ingest.schema import (
    GameRecord,
    format_clock,
    parse_clock,
    seconds_remaining,
)
from app.ingest.teams_static import BY_ABBREVIATION, TEAMS


class TestClock:
    def test_tipoff_is_a_full_game(self):
        assert seconds_remaining(1, 12 * 60) == 2880

    def test_halftime(self):
        assert seconds_remaining(2, 0) == 1440

    def test_final_buzzer(self):
        assert seconds_remaining(4, 0) == 0

    def test_overtime_runs_negative(self):
        assert seconds_remaining(5, 5 * 60) == 0  # start of OT1
        assert seconds_remaining(5, 0) == -300  # end of OT1
        assert seconds_remaining(6, 5 * 60) == -300  # start of OT2
        assert seconds_remaining(6, 0) == -600

    def test_the_axis_is_monotone_across_the_whole_game(self):
        values = []
        for period in range(1, 7):
            length = 12 * 60 if period <= 4 else 5 * 60
            for clock in range(length, -1, -60):
                values.append(seconds_remaining(period, clock))
        assert values == sorted(values, reverse=True)

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("11:32", 692.0),
            ("0:04", 4.0),
            ("0:00.3", 0.3),
            ("PT11M32.00S", 692.0),
            ("PT00M04.50S", 4.5),
            ("", 0.0),
        ],
    )
    def test_parse_clock(self, text, expected):
        assert parse_clock(text) == pytest.approx(expected)

    def test_format_clock_round_trips(self):
        for secs in (0, 4, 59, 60, 692, 720):
            assert parse_clock(format_clock(secs)) == pytest.approx(secs, abs=1)

    def test_format_clock_clamps_negative(self):
        assert format_clock(-5) == "0:00"


class TestTeams:
    def test_there_are_thirty(self):
        assert len(TEAMS) == 30

    def test_ids_and_abbreviations_are_unique(self):
        assert len({t.id for t in TEAMS}) == 30
        assert len({t.abbreviation for t in TEAMS}) == 30

    def test_ids_match_the_real_nba_range(self):
        # stats.nba.com franchise ids all live in this block; using the real
        # ones means synthetic and live data share a key space.
        assert all(1610612737 <= t.id <= 1610612766 for t in TEAMS)

    def test_lookup(self):
        assert BY_ABBREVIATION["BOS"].full_name == "Boston Celtics"


class TestSimulator:
    games = synthetic.simulate_season("TEST", n_games=60, seed=5, league_seed=4242)

    def test_every_game_has_a_winner(self):
        assert all(g.home_score != g.away_score for g in self.games)

    def test_scores_are_in_a_believable_range(self):
        totals = [g.home_score + g.away_score for g in self.games]
        mean = sum(totals) / len(totals)
        assert 195 < mean < 250, mean

    def test_margin_dispersion_is_believable(self):
        import statistics

        margins = [g.home_score - g.away_score for g in self.games]
        assert 10 < statistics.pstdev(margins) < 19

    def test_home_teams_win_more_than_half(self):
        wins = sum(1 for g in self.games if g.home_score > g.away_score)
        assert wins / len(self.games) > 0.5

    def test_play_by_play_is_internally_consistent(self):
        for g in self.games[:10]:
            prev_home = prev_away = 0
            for p in g.plays:
                assert p.score_margin == p.home_score - p.away_score
                assert p.home_score >= prev_home
                assert p.away_score >= prev_away
                prev_home, prev_away = p.home_score, p.away_score
            assert prev_home == g.home_score
            assert prev_away == g.away_score

    def test_the_clock_only_runs_forward(self):
        for g in self.games[:10]:
            secs = [p.seconds_remaining for p in g.plays]
            assert secs == sorted(secs, reverse=True)

    def test_box_score_points_match_the_final_score(self):
        for g in self.games[:10]:
            home = sum(b.points for b in g.player_box if b.team_id == g.home_team_id)
            away = sum(b.points for b in g.player_box if b.team_id == g.away_team_id)
            assert home == g.home_score
            assert away == g.away_score

    def test_overtime_games_have_extra_periods(self):
        for g in self.games:
            if g.periods > 4:
                assert any(p.period > 4 for p in g.plays)

    def test_three_point_rate_responds_to_the_shift(self):
        def rate(games):
            return sum(g.home_fg3a + g.away_fg3a for g in games) / sum(
                g.home_fga + g.away_fga for g in games
            )

        low = synthetic.simulate_season(
            "LOW", n_games=40, seed=5, three_rate_shift=-0.10, league_seed=4242
        )
        high = synthetic.simulate_season(
            "HIGH", n_games=40, seed=5, three_rate_shift=+0.10, league_seed=4242
        )
        assert rate(high) - rate(low) > 0.10

    def test_deterministic_for_a_fixed_seed(self):
        a = synthetic.simulate_season("D", n_games=3, seed=42, league_seed=1)
        b = synthetic.simulate_season("D", n_games=3, seed=42, league_seed=1)
        assert [g.home_score for g in a] == [g.home_score for g in b]
        assert [len(g.plays) for g in a] == [len(g.plays) for g in b]


class TestFixtures:
    def test_round_trip_through_gzipped_json(self, tmp_path):
        games = synthetic.simulate_season("RT", n_games=2, seed=3, league_seed=1)
        path = tmp_path / "fixture.json.gz"
        assert write_fixture(games, path) == 2

        loaded = read_fixture(path)
        assert len(loaded) == 2
        assert isinstance(loaded[0], GameRecord)
        assert loaded[0].home_score == games[0].home_score
        assert len(loaded[0].plays) == len(games[0].plays)
        assert loaded[0].plays[10].description == games[0].plays[10].description

    def test_round_trip_through_plain_json(self, tmp_path):
        games = synthetic.simulate_season("RT", n_games=1, seed=3, league_seed=1)
        path = tmp_path / "fixture.json"
        write_fixture(games, path)
        assert read_fixture(path)[0].id == games[0].id

    def test_bundled_sample_data_is_present_and_loadable(self):
        from app.config import BACKEND_ROOT

        files = sorted((BACKEND_ROOT / "data" / "sample").glob("*.json*"))
        assert files, "no bundled fixtures -- run scripts/make_fixtures.py"
        games = read_fixture(files[0])
        assert games
        assert games[0].plays


class TestNBASourceParsing:
    """The nba_api module must import and parse without the network."""

    def test_shot_parsing(self):
        from app.ingest.nba_source import _shot_distance, _shot_points

        assert _shot_points("Tatum 26' 3PT Jump Shot", 1) == (3, True)
        assert _shot_points("Tatum 18' Jump Shot", 1) == (2, False)
        assert _shot_points("MISS Tatum 26' 3PT Jump Shot", 2) == (0, True)
        assert _shot_points("Tatum Free Throw 1 of 2", 3) == (1, False)
        assert _shot_points("MISS Tatum Free Throw 2 of 2", 3) == (0, False)
        assert _shot_distance("Tatum 26' 3PT Jump Shot") == 26.0
        assert _shot_distance("Tatum Free Throw 1 of 2") is None

    def test_event_type_table_covers_the_documented_codes(self):
        from app.ingest.nba_source import EVENT_TYPES

        assert EVENT_TYPES[1] == "SHOT"
        assert EVENT_TYPES[2] == "MISS"
        assert EVENT_TYPES[3] == "FREE_THROW"
        assert set(EVENT_TYPES) == set(range(1, 14))
