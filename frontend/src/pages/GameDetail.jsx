import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../lib/api.js";
import {
  Card,
  ErrorBox,
  Loading,
  PageHead,
  Stat,
  formatGameClock,
  pct,
  periodLabel,
} from "../components/Common.jsx";

const MODELS = [
  ["blend", "Blend", "Diffusion early, possession chain late"],
  ["brownian", "Brownian", "Continuous diffusion with drift"],
  ["markov", "Markov", "Exact chain over possession states"],
];

export default function GameDetail() {
  const { gameId } = useParams();
  const [model, setModel] = useState("blend");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    setData(null);
    setError(null);
    api
      .winProbability(gameId, model)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e));
    return () => {
      alive = false;
    };
  }, [gameId, model]);

  // x axis runs left-to-right as game time elapses, so plot elapsed seconds.
  const series = useMemo(
    () =>
      (data?.points ?? []).map((p) => ({
        ...p,
        elapsed: 2880 - p.seconds_remaining,
        wp: p.win_probability,
      })),
    [data],
  );

  // Quarter starts, plus one tick per overtime period the game actually
  // reached. A fixed [0, 720, …, 2880] gives an overtime game two ticks both
  // labelled Q4.
  const ticks = useMemo(() => {
    const base = [0, 720, 1440, 2160];
    const maxElapsed = series.length ? series[series.length - 1].elapsed : 2880;
    // `< maxElapsed`, not `<=`: a game that ends exactly at the OT1 buzzer
    // would otherwise get an "OT2" tick for a period that never happened.
    for (let t = 2880; t < maxElapsed; t += 300) base.push(t);
    return base;
  }, [series]);

  const biggestSwing = useMemo(() => {
    let best = null;
    for (let i = 1; i < series.length; i++) {
      const delta = series[i].wp - series[i - 1].wp;
      if (!best || Math.abs(delta) > Math.abs(best.delta)) {
        best = { delta, play: series[i] };
      }
    }
    return best;
  }, [series]);

  if (error) {
    return (
      <>
        <PageHead title="Game" />
        <ErrorBox error={error} />
        <Link to="/games">← Back to games</Link>
      </>
    );
  }
  if (!data) return <Loading what="win probability" />;

  const { game, params } = data;
  const homeWon = game.home_score > game.away_score;

  return (
    <>
      <PageHead
        title={`${game.away.full_name} @ ${game.home.full_name}`}
      >
        {game.game_date} · {game.season} · final {game.away_score}–
        {game.home_score}
        {game.periods > 4 ? ` (${game.periods - 4}OT)` : ""}
      </PageHead>

      <Link to="/games" className="muted">
        ← All games
      </Link>

      <Card
        title={`${game.home.abbreviation} win probability`}
        sub={MODELS.find(([k]) => k === model)?.[2]}
      >
        <div className="row" style={{ marginBottom: 14 }}>
          {MODELS.map(([key, label]) => (
            <button
              key={key}
              className={model === key ? "" : "ghost"}
              onClick={() => setModel(key)}
            >
              {label}
            </button>
          ))}
        </div>

        <div style={{ width: "100%", height: 320 }}>
          <ResponsiveContainer>
            <AreaChart data={series} margin={{ top: 6, right: 10, bottom: 6, left: -18 }}>
              <defs>
                <linearGradient id="wpFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#4c8dff" stopOpacity={0.55} />
                  <stop offset="100%" stopColor="#4c8dff" stopOpacity={0.03} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#262d3a" vertical={false} />
              <XAxis
                dataKey="elapsed"
                type="number"
                domain={[0, "dataMax"]}
                ticks={ticks}
                tickFormatter={periodLabel}
                stroke="#8b95a7"
                fontSize={12}
              />
              <YAxis
                domain={[0, 1]}
                ticks={[0, 0.25, 0.5, 0.75, 1]}
                tickFormatter={(v) => `${v * 100}%`}
                stroke="#8b95a7"
                fontSize={12}
              />
              <ReferenceLine y={0.5} stroke="#4a5468" strokeDasharray="4 4" />
              <Tooltip
                contentStyle={{
                  background: "#141922",
                  border: "1px solid #262d3a",
                  borderRadius: 8,
                  fontSize: 13,
                }}
                labelFormatter={() => ""}
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const p = payload[0].payload;
                  return (
                    <div
                      style={{
                        background: "#141922",
                        border: "1px solid #262d3a",
                        borderRadius: 8,
                        padding: "8px 10px",
                        fontSize: 13,
                        maxWidth: 280,
                      }}
                    >
                      <div className="muted" style={{ fontSize: 12 }}>
                        {formatGameClock(p.seconds_remaining)} ·{" "}
                        {game.away.abbreviation} {p.away_score} –{" "}
                        {p.home_score} {game.home.abbreviation}
                      </div>
                      <div style={{ fontWeight: 600, margin: "3px 0" }}>
                        {game.home.abbreviation} {pct(p.wp)}
                      </div>
                      <div className="muted" style={{ fontSize: 12 }}>
                        {p.description}
                      </div>
                    </div>
                  );
                }}
              />
              <Area
                type="stepAfter"
                dataKey="wp"
                stroke="#4c8dff"
                strokeWidth={1.8}
                fill="url(#wpFill)"
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <p className="muted" style={{ fontSize: 12.5, marginBottom: 0 }}>
          The shaded area is {game.home.abbreviation}&apos;s win probability;
          50% is a coin flip. {homeWon ? game.home.abbreviation : game.away.abbreviation}{" "}
          won, so the curve ends at {homeWon ? "100%" : "0%"}.
        </p>
      </Card>

      <div className="grid" style={{ marginBottom: 18 }}>
        <Stat
          label="Fitted drift μ"
          value={`${params.mu >= 0 ? "+" : ""}${params.mu.toFixed(2)}`}
          note={`Home edge, points/game · ${params.n_games} games`}
        />
        <Stat
          label="Fitted σ"
          value={params.sigma.toFixed(2)}
          note="SD of final margin"
        />
        <Stat label="Plays scored" value={series.length} />
        {biggestSwing ? (
          <Stat
            label="Biggest swing"
            value={`${biggestSwing.delta > 0 ? "+" : ""}${(
              biggestSwing.delta * 100
            ).toFixed(1)} pts`}
            note={formatGameClock(biggestSwing.play.seconds_remaining)}
          />
        ) : null}
      </div>

      <Card title="Highest-leverage moments" sub="Where the game was actually decided">
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th>Clock</th>
                <th className="num">Score</th>
                <th className="num">Win prob</th>
                <th className="num">Leverage</th>
                <th>Play</th>
              </tr>
            </thead>
            <tbody>
              {[...series]
                .sort((a, b) => b.leverage - a.leverage)
                .slice(0, 12)
                .map((p) => (
                  <tr key={p.event_num}>
                    <td>{formatGameClock(p.seconds_remaining)}</td>
                    <td className="num">
                      {p.away_score}–{p.home_score}
                    </td>
                    <td className="num">{pct(p.wp)}</td>
                    <td className="num">{pct(p.leverage)}</td>
                    <td
                      className="muted"
                      style={{ whiteSpace: "normal", minWidth: 240 }}
                    >
                      {p.description}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        <p className="muted" style={{ fontSize: 12.5, margin: "10px 0 0" }}>
          Leverage is how much win probability a single made three would move
          from that state — a measure of how much the moment mattered,
          independent of what actually happened.
        </p>
      </Card>
    </>
  );
}
