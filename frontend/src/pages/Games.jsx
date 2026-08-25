import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api.js";
import { Card, ErrorBox, Loading, PageHead } from "../components/Common.jsx";

export default function Games() {
  const [games, setGames] = useState(null);
  const [error, setError] = useState(null);
  const [season, setSeason] = useState("");
  const [team, setTeam] = useState("");

  useEffect(() => {
    let alive = true;
    setGames(null);
    api
      .games({ season, team, limit: 60 })
      .then((g) => alive && setGames(g))
      .catch((e) => alive && setError(e));
    return () => {
      alive = false;
    };
  }, [season, team]);

  const seasons = [...new Set((games ?? []).map((g) => g.season))];

  return (
    <>
      <PageHead title="Games">
        Pick a game to see its win-probability path. Every point on the curve is
        the model&apos;s answer using only what was known at that moment.
      </PageHead>

      <ErrorBox error={error} />

      <Card>
        <div className="row">
          <label className="field">
            Season
            <input
              placeholder="e.g. 2023-24S"
              value={season}
              onChange={(e) => setSeason(e.target.value.trim())}
            />
          </label>
          <label className="field">
            Team
            <input
              placeholder="e.g. BOS"
              value={team}
              maxLength={3}
              onChange={(e) => setTeam(e.target.value.toUpperCase().trim())}
            />
          </label>
          {season || team ? (
            <button
              className="ghost"
              onClick={() => {
                setSeason("");
                setTeam("");
              }}
            >
              Clear
            </button>
          ) : null}
          {seasons.length ? (
            <span className="pill" style={{ marginLeft: "auto" }}>
              {seasons.join(" · ")}
            </span>
          ) : null}
        </div>
      </Card>

      <Card title="Results" sub={games ? `${games.length} games` : ""}>
        {games === null ? (
          <Loading what="games" />
        ) : games.length === 0 ? (
          <p className="muted">
            No games matched. If the database is empty, run{" "}
            <code className="mono">python -m app.ingest.cli seed</code>.
          </p>
        ) : (
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Season</th>
                  <th>Matchup</th>
                  <th className="num">Score</th>
                  <th>Result</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {games.map((g) => {
                  const homeWon = g.home_score > g.away_score;
                  return (
                    <tr key={g.id}>
                      <td>{g.game_date}</td>
                      <td className="muted">{g.season}</td>
                      <td>
                        {g.away.abbreviation} @ <b>{g.home.abbreviation}</b>
                        {g.periods > 4 ? (
                          <span className="pill" style={{ marginLeft: 8 }}>
                            {g.periods === 5 ? "OT" : `${g.periods - 4}OT`}
                          </span>
                        ) : null}
                      </td>
                      <td className="num">
                        {g.away_score}–{g.home_score}
                      </td>
                      <td
                        style={{
                          color: homeWon ? "var(--good)" : "var(--accent-2)",
                        }}
                      >
                        {homeWon ? g.home.abbreviation : g.away.abbreviation} by{" "}
                        {Math.abs(g.home_score - g.away_score)}
                      </td>
                      <td>
                        <Link to={`/games/${g.id}`}>Win probability →</Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
