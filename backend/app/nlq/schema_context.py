"""The schema description handed to the model.

Kept as a hand-written document rather than a dump of ``CREATE TABLE``
statements: the model needs the *semantics* (that ``seconds_remaining`` counts
down through regulation, that ``score_margin`` is home-relative) far more than
it needs the column types.
"""

SCHEMA_DOC = """\
You write SQLite queries against an NBA play-by-play database.

TABLES
------
teams(id INTEGER PK, abbreviation TEXT, full_name TEXT, conference TEXT)

games(
  id TEXT PK,                -- NBA game id, e.g. '0022300561'
  season TEXT,               -- '2023-24'
  season_type TEXT,          -- 'Regular Season' | 'Playoffs'
  game_date TEXT,            -- 'YYYY-MM-DD'
  home_team_id INTEGER -> teams.id,
  away_team_id INTEGER -> teams.id,
  home_score INTEGER, away_score INTEGER,
  periods INTEGER,           -- 4 in regulation, 5+ means overtime
  home_fga, home_fg3a, home_fg3m, home_fta, home_oreb, home_tov,
  away_fga, away_fg3a, away_fg3m, away_fta, away_oreb, away_tov
)

plays(
  id INTEGER PK,
  game_id TEXT -> games.id,
  event_num INTEGER,         -- ordering within the game
  period INTEGER,            -- 1-4 regulation, 5+ overtime
  clock TEXT,                -- 'MM:SS' remaining in the period
  seconds_remaining INTEGER, -- seconds left in REGULATION; 0 at the buzzer,
                             -- negative during overtime. 2880 at tip-off.
  event_type TEXT,           -- 'SHOT','MISS','FREE_THROW','REBOUND',
                             -- 'TURNOVER','FOUL','SUB','TIMEOUT','PERIOD_END'
  description TEXT,
  team_id INTEGER -> teams.id,   -- team responsible for the event; may be NULL
  player_name TEXT,
  home_score INTEGER, away_score INTEGER,
  score_margin INTEGER,      -- home_score - away_score AFTER this event
  points INTEGER,            -- points scored on this event (0,1,2,3)
  shot_distance REAL,        -- feet; NULL for non-shots
  is_three INTEGER           -- 1 if a three-point attempt
)

player_box(
  id INTEGER PK, game_id TEXT -> games.id, team_id INTEGER -> teams.id,
  player_name TEXT, minutes REAL, points INTEGER, rebounds INTEGER,
  assists INTEGER, fg3a INTEGER, fg3m INTEGER
)

CONVENTIONS
-----------
* "Clutch" means the final 5 minutes of regulation with the score within 5:
  `seconds_remaining <= 300 AND ABS(score_margin) <= 5`.
* A made shot is `event_type='SHOT'` (points > 0); a miss is
  `event_type='MISS'` (points = 0).
* To attribute a play to a home or away team, join `plays.team_id` against
  `games.home_team_id` / `games.away_team_id`.
* Three-point rate = fg3a / fga. Possessions ~=
  `fga + 0.44*fta - oreb + tov`, averaged across the two teams.
* Always give computed columns a readable alias.

RULES
-----
* Output ONE SQLite SELECT statement and nothing else -- no prose, no
  markdown fences, no trailing semicolon.
* Only the tables above may be referenced. There is no user or account table.
* Never use INSERT/UPDATE/DELETE/DROP/ALTER/PRAGMA/ATTACH.
* Always include a LIMIT (default 100) unless the query is a single aggregate.
"""

FEW_SHOTS = [
    (
        "Which players took the most threes in the final two minutes of close games?",
        """SELECT p.player_name,
       COUNT(*) AS clutch_threes_attempted,
       SUM(CASE WHEN p.event_type = 'SHOT' THEN 1 ELSE 0 END) AS made
FROM plays p
WHERE p.is_three = 1
  AND p.seconds_remaining <= 120
  AND ABS(p.score_margin) <= 5
  AND p.player_name IS NOT NULL
GROUP BY p.player_name
ORDER BY clutch_threes_attempted DESC
LIMIT 20""",
    ),
    (
        "How has three point rate changed by season?",
        """SELECT g.season,
       COUNT(*) AS games,
       ROUND(1.0 * SUM(g.home_fg3a + g.away_fg3a)
             / NULLIF(SUM(g.home_fga + g.away_fga), 0), 4) AS three_point_rate
FROM games g
GROUP BY g.season
ORDER BY g.season""",
    ),
]


def build_prompt(question: str) -> str:
    shots = "\n\n".join(
        f"Question: {q}\nSQL:\n{sql}" for q, sql in FEW_SHOTS
    )
    return (
        f"{SCHEMA_DOC}\n\nEXAMPLES\n--------\n{shots}\n\n"
        f"Question: {question}\nSQL:\n"
    )
