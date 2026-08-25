"""End-to-end API tests: auth, authorization, and every analytics endpoint."""

from __future__ import annotations

import pytest

from app.security import (
    PasswordPolicyError,
    create_access_token,
    hash_password,
    validate_password,
    verify_password,
)


class TestHealth:
    def test_health_is_public(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_security_headers_are_set(self, client):
        r = client.get("/health")
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"


class TestPasswords:
    def test_hash_is_salted(self):
        a = hash_password("correct-horse-9")
        b = hash_password("correct-horse-9")
        assert a != b, "identical passwords must not produce identical hashes"
        assert verify_password("correct-horse-9", a)
        assert verify_password("correct-horse-9", b)

    def test_wrong_password_fails(self):
        h = hash_password("correct-horse-9")
        assert not verify_password("correct-horse-8", h)

    def test_malformed_hash_returns_false_rather_than_raising(self):
        assert verify_password("anything", "not-a-bcrypt-hash") is False

    @pytest.mark.parametrize(
        "bad", ["short1", "alllettersnodigits", "1234567890", "a" * 200]
    )
    def test_policy_rejects_weak_passwords(self, bad):
        with pytest.raises(PasswordPolicyError):
            validate_password(bad)

    def test_policy_accepts_a_reasonable_password(self):
        validate_password("correct-horse-9")


class TestAuth:
    def test_register_then_use_the_token(self, client):
        r = client.post(
            "/api/auth/register",
            json={"email": "first@example.com", "password": "correct-horse-9"},
        )
        assert r.status_code == 201, r.text
        token = r.json()["access_token"]
        assert r.json()["expires_in"] > 0

        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["email"] == "first@example.com"

    def test_duplicate_email_is_a_conflict(self, client):
        payload = {"email": "dupe@example.com", "password": "correct-horse-9"}
        assert client.post("/api/auth/register", json=payload).status_code == 201
        assert client.post("/api/auth/register", json=payload).status_code == 409

    def test_email_is_normalised_to_lowercase(self, client):
        client.post(
            "/api/auth/register",
            json={"email": "Mixed@Example.com", "password": "correct-horse-9"},
        )
        r = client.post(
            "/api/auth/login",
            json={"email": "mixed@example.com", "password": "correct-horse-9"},
        )
        assert r.status_code == 200

    def test_weak_password_is_rejected_at_registration(self, client):
        r = client.post(
            "/api/auth/register", json={"email": "weak@example.com", "password": "abc"}
        )
        assert r.status_code == 422

    def test_login_with_the_wrong_password_fails(self, client):
        client.post(
            "/api/auth/register",
            json={"email": "login@example.com", "password": "correct-horse-9"},
        )
        r = client.post(
            "/api/auth/login",
            json={"email": "login@example.com", "password": "wrong-horse-9"},
        )
        assert r.status_code == 401

    def test_unknown_account_and_wrong_password_are_indistinguishable(self, client):
        a = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "correct-horse-9"},
        )
        b = client.post(
            "/api/auth/login",
            json={"email": "login@example.com", "password": "wrong-horse-9"},
        )
        assert a.status_code == b.status_code == 401
        assert a.json()["detail"] == b.json()["detail"]


class TestAuthorization:
    PROTECTED = [
        ("GET", "/api/games"),
        ("GET", "/api/trends/seasons"),
        ("GET", "/api/trends/project"),
        ("GET", "/api/auth/me"),
        ("GET", "/api/nlq/schema"),
        ("GET", "/api/calibration/compare"),
    ]

    @pytest.mark.parametrize("method,path", PROTECTED)
    def test_requires_a_token(self, client, method, path):
        r = client.request(method, path)
        assert r.status_code == 401, f"{path} is not protected"

    @pytest.mark.parametrize("method,path", PROTECTED)
    def test_rejects_a_garbage_token(self, client, method, path):
        r = client.request(method, path, headers={"Authorization": "Bearer nonsense"})
        assert r.status_code == 401

    def test_rejects_a_token_signed_with_the_wrong_key(self, client):
        import jwt

        forged = jwt.encode(
            {"sub": "analyst@example.com", "typ": "access", "exp": 9999999999},
            "the-wrong-secret",
            algorithm="HS256",
        )
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
        assert r.status_code == 401

    def test_rejects_an_expired_token(self, client, monkeypatch):
        from app.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "access_token_ttl_minutes", -1)
        token, _ = create_access_token("analyst@example.com")
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

    def test_rejects_a_token_for_a_user_that_does_not_exist(self, client):
        token, _ = create_access_token("ghost@example.com")
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

    def test_nlq_requires_auth(self, client):
        r = client.post("/api/nlq/query", json={"question": "how many games?"})
        assert r.status_code == 401


class TestGames:
    def test_list_games(self, auth_client):
        r = auth_client.get("/api/games?limit=5")
        assert r.status_code == 200
        games = r.json()
        assert games
        assert {"id", "season", "home", "away", "home_score"} <= set(games[0])

    def test_filter_by_season(self, auth_client):
        r = auth_client.get("/api/games?season=2023-24T&limit=50")
        assert r.status_code == 200
        assert all(g["season"] == "2023-24T" for g in r.json())

    def test_unknown_game_is_404(self, auth_client):
        assert auth_client.get("/api/games/does-not-exist").status_code == 404

    def test_plays_are_ordered_and_consistent(self, auth_client, sample_game_id):
        r = auth_client.get(f"/api/games/{sample_game_id}/plays?limit=2000")
        assert r.status_code == 200
        plays = r.json()
        assert plays
        assert [p["event_num"] for p in plays] == sorted(
            p["event_num"] for p in plays
        )
        for p in plays:
            assert p["score_margin"] == p["home_score"] - p["away_score"]

    def test_win_probability_curve(self, auth_client, sample_game_id):
        r = auth_client.get(f"/api/games/{sample_game_id}/win-probability")
        assert r.status_code == 200
        body = r.json()
        points = body["points"]
        assert len(points) > 50
        assert all(0.0 <= p["win_probability"] <= 1.0 for p in points)

        # The curve must resolve to the actual result by the final event.
        game = body["game"]
        home_won = game["home_score"] > game["away_score"]
        final = points[-1]["win_probability"]
        assert (final > 0.9) if home_won else (final < 0.1), final

    @pytest.mark.parametrize("model", ["brownian", "markov", "blend"])
    def test_every_model_produces_a_curve(self, auth_client, sample_game_id, model):
        r = auth_client.get(
            f"/api/games/{sample_game_id}/win-probability?model={model}"
        )
        assert r.status_code == 200
        assert r.json()["model"] == model

    def test_rejects_an_unknown_model(self, auth_client, sample_game_id):
        r = auth_client.get(f"/api/games/{sample_game_id}/win-probability?model=magic")
        assert r.status_code == 422

    def test_ad_hoc_state_scoring(self, auth_client):
        r = auth_client.post(
            "/api/games/win-probability/state",
            json={"margin": 3, "seconds_remaining": 24, "home_has_ball": True},
        )
        assert r.status_code == 200
        body = r.json()
        assert 0.5 < body["win_probability"] < 1.0
        assert body["source"] in {"python", "java-sim", "python-fallback"}

    def test_state_scoring_validates_its_inputs(self, auth_client):
        r = auth_client.post(
            "/api/games/win-probability/state",
            json={"margin": 3, "seconds_remaining": 99999},
        )
        assert r.status_code == 422


class TestTrends:
    def test_season_trends(self, auth_client):
        r = auth_client.get("/api/trends/seasons")
        assert r.status_code == 200
        seasons = r.json()["seasons"]
        assert len(seasons) >= 2
        for s in seasons:
            assert 80 < s["pace"] < 120, s
            assert 0.15 < s["three_point_rate"] < 0.75, s
            assert 90 < s["points_per_100"] < 135, s

    def test_projection_extends_the_series(self, auth_client):
        r = auth_client.get("/api/trends/project?metric=three_point_rate&horizon=3")
        assert r.status_code == 200
        body = r.json()
        assert len(body["projected"]) == 3
        for p in body["projected"]:
            assert p["lower"] <= p["value"] <= p["upper"]

    def test_projection_rejects_an_unknown_metric(self, auth_client):
        assert auth_client.get("/api/trends/project?metric=vibes").status_code == 422


class TestNLQ:
    def test_schema_endpoint_never_lists_the_users_table(self, auth_client):
        r = auth_client.get("/api/nlq/schema")
        assert r.status_code == 200
        assert "users" not in r.json()["tables"]

    def test_rule_based_provider_answers_a_known_question(self, auth_client):
        r = auth_client.post(
            "/api/nlq/query",
            json={"question": "How has three point rate changed by season?"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["provider"] == "rule-based"
        assert "three_point_rate" in body["columns"]
        assert body["rows"]

    def test_clutch_question(self, auth_client):
        r = auth_client.post(
            "/api/nlq/query", json={"question": "who are the best clutch scorers?"}
        )
        assert r.status_code == 200
        assert "clutch_points" in r.json()["columns"]

    def test_generated_sql_is_returned_for_inspection(self, auth_client):
        r = auth_client.post("/api/nlq/query", json={"question": "pace by season"})
        sql = r.json()["sql"].lower()
        assert sql.startswith("select")
        assert "limit" in sql

    def test_question_length_is_validated(self, auth_client):
        assert (
            auth_client.post("/api/nlq/query", json={"question": "a"}).status_code == 422
        )
        assert (
            auth_client.post(
                "/api/nlq/query", json={"question": "x" * 5000}
            ).status_code
            == 422
        )

    def test_a_hostile_provider_cannot_get_past_the_guardrails(
        self, auth_client, monkeypatch
    ):
        """The provider is not trusted, so simulate one that has been hijacked."""
        from app.nlq import provider as provider_module

        class Hostile(provider_module.TextToSQLProvider):
            name = "hostile"

            def generate(self, question: str) -> str:
                return "DROP TABLE users"

        monkeypatch.setattr(provider_module, "get_provider", lambda: Hostile())
        monkeypatch.setattr("app.routers.nlq.get_provider", lambda: Hostile())

        r = auth_client.post("/api/nlq/query", json={"question": "anything"})
        assert r.status_code == 400
        assert "SELECT" in r.json()["detail"]

        # And the table is still there.
        assert auth_client.get("/api/auth/me").status_code == 200


class TestCalibration:
    def test_backtest_reports_sane_metrics(self, auth_client):
        r = auth_client.post(
            "/api/calibration/backtest",
            json={"model": "blend", "stride_seconds": 120, "n_bins": 5},
        )
        assert r.status_code == 200
        body = r.json()
        overall = body["overall"]
        assert 0.0 <= overall["brier"] <= 0.25
        assert overall["n"] > 0
        assert len(overall["bins"]) == 5
        assert sum(b["count"] for b in overall["bins"]) == overall["n"]

    def test_compare_runs_every_model(self, auth_client):
        r = auth_client.get("/api/calibration/compare?stride_seconds=180")
        assert r.status_code == 200
        models = r.json()["models"]
        assert set(models) == {"brownian", "markov", "blend"}
        for name, m in models.items():
            assert 0.0 <= m["brier"] <= 0.25, name

    def test_fitted_possession_model_is_plausible(self, auth_client):
        r = auth_client.get("/api/calibration/possession-model")
        assert r.status_code == 200
        ppp = r.json()["model"]["points_per_possession"]
        assert 0.8 < ppp < 1.5, ppp
