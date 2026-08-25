"""Text-to-SQL providers.

Two implementations behind one interface:

* :class:`AnthropicProvider` -- the real thing. Sends the schema document and
  a couple of worked examples, asks for one SELECT statement back.
* :class:`RuleBasedProvider` -- a small pattern matcher over a handful of
  common questions. It exists so the test suite, CI, and a fresh clone with no
  API key still produce working answers instead of a 500.

Whichever produces the SQL, it goes through ``guardrails.validate`` before it
touches the database. The provider is never trusted.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod

from app.config import get_settings
from app.nlq.schema_context import build_prompt

log = logging.getLogger(__name__)


class TextToSQLProvider(ABC):
    name: str

    @abstractmethod
    def generate(self, question: str) -> str:
        """Return a single SQL SELECT statement (unvalidated)."""

    def explain(self, question: str, sql: str, columns: list[str], rows: list) -> str:
        del question, sql
        return f"Returned {len(rows)} row(s) with columns: {', '.join(columns)}."


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------
class AnthropicProvider(TextToSQLProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        import anthropic  # imported lazily so the package stays optional

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def generate(self, question: str) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=800,
            system=(
                "You translate questions about NBA play-by-play data into "
                "SQLite SELECT statements. Reply with the SQL only."
            ),
            messages=[{"role": "user", "content": build_prompt(question)}],
        )
        text = "".join(
            block.text for block in msg.content if getattr(block, "type", "") == "text"
        )
        return text.strip()

    def explain(self, question: str, sql: str, columns: list[str], rows: list) -> str:
        preview = rows[:15]
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=350,
            system=(
                "You explain query results to a basketball analyst in two or "
                "three sentences. Be concrete, cite numbers from the rows, and "
                "do not describe the SQL itself."
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Question: {question}\nSQL: {sql}\n"
                        f"Columns: {columns}\nRows (first 15): {preview}"
                    ),
                }
            ],
        )
        return "".join(
            b.text for b in msg.content if getattr(b, "type", "") == "text"
        ).strip()


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"three.?point rate|3p.?rate|threes? per|three.?point attempt", re.I),
        """SELECT g.season,
       COUNT(*) AS games,
       ROUND(1.0 * SUM(g.home_fg3a + g.away_fg3a)
             / NULLIF(SUM(g.home_fga + g.away_fga), 0), 4) AS three_point_rate,
       ROUND(1.0 * SUM(g.home_fg3m + g.away_fg3m)
             / NULLIF(SUM(g.home_fg3a + g.away_fg3a), 0), 4) AS three_point_pct
FROM games g
GROUP BY g.season
ORDER BY g.season
LIMIT 100""",
    ),
    (
        re.compile(r"\bpace\b|possessions per", re.I),
        """SELECT g.season,
       COUNT(*) AS games,
       ROUND(AVG(0.5 * ((g.home_fga + 0.44*g.home_fta - g.home_oreb + g.home_tov)
                      + (g.away_fga + 0.44*g.away_fta - g.away_oreb + g.away_tov))), 2)
         AS possessions_per_game
FROM games g
GROUP BY g.season
ORDER BY g.season
LIMIT 100""",
    ),
    (
        re.compile(r"clutch", re.I),
        """SELECT p.player_name,
       COUNT(*) AS clutch_shots,
       SUM(p.points) AS clutch_points
FROM plays p
WHERE p.seconds_remaining <= 300
  AND ABS(p.score_margin) <= 5
  AND p.event_type IN ('SHOT','MISS')
  AND p.player_name IS NOT NULL
GROUP BY p.player_name
ORDER BY clutch_points DESC
LIMIT 25""",
    ),
    (
        re.compile(r"home (court|team).*(advantage|win)|win rate", re.I),
        """SELECT g.season,
       COUNT(*) AS games,
       ROUND(AVG(CASE WHEN g.home_score > g.away_score THEN 1.0 ELSE 0.0 END), 4)
         AS home_win_rate,
       ROUND(AVG(g.home_score - g.away_score), 2) AS avg_home_margin
FROM games g
GROUP BY g.season
ORDER BY g.season
LIMIT 100""",
    ),
    (
        re.compile(r"overtime|\bot\b", re.I),
        """SELECT g.season,
       SUM(CASE WHEN g.periods > 4 THEN 1 ELSE 0 END) AS overtime_games,
       COUNT(*) AS games
FROM games g
GROUP BY g.season
ORDER BY g.season
LIMIT 100""",
    ),
    (
        re.compile(r"highest scoring|most points|top scorer", re.I),
        """SELECT b.player_name,
       SUM(b.points) AS total_points,
       COUNT(*) AS games,
       ROUND(1.0 * SUM(b.points) / COUNT(*), 2) AS points_per_game
FROM player_box b
GROUP BY b.player_name
ORDER BY total_points DESC
LIMIT 25""",
    ),
    (
        re.compile(r"closest|biggest comeback|largest lead", re.I),
        """SELECT g.id AS game_id, g.game_date,
       ht.abbreviation AS home, at.abbreviation AS away,
       g.home_score, g.away_score,
       ABS(g.home_score - g.away_score) AS final_margin
FROM games g
JOIN teams ht ON ht.id = g.home_team_id
JOIN teams at ON at.id = g.away_team_id
ORDER BY final_margin ASC
LIMIT 25""",
    ),
]

_FALLBACK_SQL = """SELECT g.id AS game_id, g.season, g.game_date,
       ht.abbreviation AS home, at.abbreviation AS away,
       g.home_score, g.away_score
FROM games g
JOIN teams ht ON ht.id = g.home_team_id
JOIN teams at ON at.id = g.away_team_id
ORDER BY g.game_date DESC
LIMIT 25"""


class RuleBasedProvider(TextToSQLProvider):
    name = "rule-based"

    def generate(self, question: str) -> str:
        for pattern, sql in _PATTERNS:
            if pattern.search(question):
                return sql
        return _FALLBACK_SQL

    def explain(self, question: str, sql: str, columns: list[str], rows: list) -> str:
        del sql
        matched = any(p.search(question) for p, _ in _PATTERNS)
        note = (
            ""
            if matched
            else " No template matched the question, so this is the default "
            "recent-games view -- set CLUTCH_ANTHROPIC_API_KEY for real "
            "text-to-SQL."
        )
        return (
            f"Returned {len(rows)} row(s): {', '.join(columns)}."
            f"{note}"
        )


# ---------------------------------------------------------------------------
def get_provider() -> TextToSQLProvider:
    settings = get_settings()
    if settings.anthropic_api_key:
        try:
            return AnthropicProvider(
                settings.anthropic_api_key, settings.anthropic_model
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Anthropic provider unavailable (%s); using rules", exc)
    return RuleBasedProvider()
