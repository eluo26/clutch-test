"""The 30 franchises, with the real stats.nba.com team ids.

Hard-coded so the synthetic fixtures use the same ids as a live nba_api pull,
which means sample data and real data can sit in the same database without
colliding or needing a translation layer.
"""

from __future__ import annotations

from app.ingest.schema import TeamRecord

TEAMS: list[TeamRecord] = [
    TeamRecord(1610612737, "ATL", "Atlanta Hawks", "East"),
    TeamRecord(1610612738, "BOS", "Boston Celtics", "East"),
    TeamRecord(1610612739, "CLE", "Cleveland Cavaliers", "East"),
    TeamRecord(1610612740, "NOP", "New Orleans Pelicans", "West"),
    TeamRecord(1610612741, "CHI", "Chicago Bulls", "East"),
    TeamRecord(1610612742, "DAL", "Dallas Mavericks", "West"),
    TeamRecord(1610612743, "DEN", "Denver Nuggets", "West"),
    TeamRecord(1610612744, "GSW", "Golden State Warriors", "West"),
    TeamRecord(1610612745, "HOU", "Houston Rockets", "West"),
    TeamRecord(1610612746, "LAC", "LA Clippers", "West"),
    TeamRecord(1610612747, "LAL", "Los Angeles Lakers", "West"),
    TeamRecord(1610612748, "MIA", "Miami Heat", "East"),
    TeamRecord(1610612749, "MIL", "Milwaukee Bucks", "East"),
    TeamRecord(1610612750, "MIN", "Minnesota Timberwolves", "West"),
    TeamRecord(1610612751, "BKN", "Brooklyn Nets", "East"),
    TeamRecord(1610612752, "NYK", "New York Knicks", "East"),
    TeamRecord(1610612753, "ORL", "Orlando Magic", "East"),
    TeamRecord(1610612754, "IND", "Indiana Pacers", "East"),
    TeamRecord(1610612755, "PHI", "Philadelphia 76ers", "East"),
    TeamRecord(1610612756, "PHX", "Phoenix Suns", "West"),
    TeamRecord(1610612757, "POR", "Portland Trail Blazers", "West"),
    TeamRecord(1610612758, "SAC", "Sacramento Kings", "West"),
    TeamRecord(1610612759, "SAS", "San Antonio Spurs", "West"),
    TeamRecord(1610612760, "OKC", "Oklahoma City Thunder", "West"),
    TeamRecord(1610612761, "TOR", "Toronto Raptors", "East"),
    TeamRecord(1610612762, "UTA", "Utah Jazz", "West"),
    TeamRecord(1610612763, "MEM", "Memphis Grizzlies", "West"),
    TeamRecord(1610612764, "WAS", "Washington Wizards", "East"),
    TeamRecord(1610612765, "DET", "Detroit Pistons", "East"),
    TeamRecord(1610612766, "CHA", "Charlotte Hornets", "East"),
]

BY_ABBREVIATION = {t.abbreviation: t for t in TEAMS}
BY_ID = {t.id: t for t in TEAMS}
