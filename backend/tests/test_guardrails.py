"""The SQL guardrails are the security boundary for the LLM layer.

Every test here is an attack the model could plausibly be talked into
emitting -- either by a user asking a leading question or by prompt injection
riding in on a column value.
"""

from __future__ import annotations

import pytest

from app.nlq.guardrails import SQLGuardrailError, normalize, validate


def rejects(sql: str) -> str:
    with pytest.raises(SQLGuardrailError) as exc:
        validate(sql)
    return str(exc.value)


class TestRejection:
    @pytest.mark.parametrize(
        "sql",
        [
            "DROP TABLE users",
            "DELETE FROM games",
            "UPDATE users SET password_hash = 'x'",
            "INSERT INTO teams VALUES (1, 'X', 'X', 'E')",
            "ALTER TABLE games ADD COLUMN x INT",
            "CREATE TABLE evil (id INT)",
            "PRAGMA table_info(users)",
            "ATTACH DATABASE '/etc/passwd' AS leak",
            "VACUUM",
        ],
    )
    def test_non_select_statements(self, sql):
        rejects(sql)

    def test_stacked_statements(self):
        rejects("SELECT 1 FROM games; DROP TABLE users")

    def test_stacked_statement_hidden_behind_a_comment(self):
        rejects("SELECT * FROM games -- ok\n; DELETE FROM plays")

    def test_write_hidden_in_a_cte(self):
        rejects("WITH x AS (DELETE FROM plays RETURNING *) SELECT * FROM x")

    def test_user_table_is_unreachable(self):
        msg = rejects("SELECT email, password_hash FROM users")
        assert "not queryable" in msg

    def test_user_table_unreachable_through_a_join(self):
        rejects("SELECT g.id, u.email FROM games g JOIN users u ON 1=1")

    def test_user_table_unreachable_through_a_subquery(self):
        rejects("SELECT (SELECT email FROM users LIMIT 1) AS leak FROM games")

    def test_sqlite_internal_tables_are_unreachable(self):
        rejects("SELECT name FROM sqlite_master")

    def test_file_functions_are_blocked(self):
        rejects("SELECT readfile('/etc/passwd') FROM games")
        rejects("SELECT load_extension('evil.so') FROM games")

    def test_select_into_is_blocked(self):
        rejects("SELECT * INTO outfile '/tmp/x' FROM games")

    def test_empty_and_garbage(self):
        rejects("")
        rejects("   \n  ")
        rejects("this is not sql at all")

    def test_query_with_no_known_table(self):
        rejects("SELECT 1")


class TestAcceptance:
    def test_plain_select(self):
        out = validate("SELECT * FROM games")
        assert out.lower().startswith("select")
        assert "LIMIT" in out

    def test_existing_limit_is_respected(self):
        out = validate("SELECT * FROM games LIMIT 7")
        assert out.count("LIMIT") == 1
        assert out.strip().endswith("LIMIT 7")

    def test_limit_is_injected_when_missing(self):
        out = validate("SELECT * FROM plays", row_limit=42)
        assert out.strip().endswith("LIMIT 42")

    def test_cte_over_allowed_tables(self):
        sql = """
        WITH clutch AS (
            SELECT game_id, player_name, points
            FROM plays
            WHERE seconds_remaining <= 300 AND ABS(score_margin) <= 5
        )
        SELECT player_name, SUM(points) AS pts FROM clutch GROUP BY player_name
        """
        assert "clutch" in validate(sql).lower()

    def test_joins_across_allowed_tables(self):
        sql = """
        SELECT t.abbreviation, COUNT(*) AS n
        FROM games g JOIN teams t ON t.id = g.home_team_id
        GROUP BY t.abbreviation
        """
        validate(sql)

    def test_replace_string_function_is_allowed(self):
        # `replace` is a legitimate SQLite function; blocking it as a keyword
        # would be a false positive, since REPLACE INTO is already unreachable.
        validate("SELECT replace(description, 'MISS ', '') AS d FROM plays")

    def test_string_literal_containing_a_keyword_is_fine(self):
        validate("SELECT * FROM plays WHERE description = 'drop step'")

    def test_markdown_fences_are_stripped(self):
        out = normalize("```sql\nSELECT * FROM games\n```")
        assert out == "SELECT * FROM games"

    def test_trailing_semicolon_is_stripped(self):
        assert normalize("SELECT * FROM games;") == "SELECT * FROM games"


class TestExecution:
    def test_read_only_connection_rejects_writes(self, seeded_db):
        """Defence in depth: even if validation were bypassed, the handle is ro."""
        from app.config import get_settings
        from app.nlq.guardrails import execute_readonly

        with pytest.raises(SQLGuardrailError):
            execute_readonly(
                "CREATE TABLE evil (id INT)", get_settings().database_url
            )

    def test_row_limit_is_enforced_at_the_cursor(self, seeded_db):
        from app.config import get_settings
        from app.nlq.guardrails import execute_readonly

        result = execute_readonly(
            "SELECT * FROM plays", get_settings().database_url, row_limit=5
        )
        assert len(result.rows) == 5
        assert result.truncated is True

    def test_returns_column_names(self, seeded_db):
        from app.config import get_settings
        from app.nlq.guardrails import execute_readonly

        result = execute_readonly(
            "SELECT season, COUNT(*) AS n FROM games GROUP BY season",
            get_settings().database_url,
        )
        assert result.columns == ["season", "n"]
        assert result.rows
