import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../lib/api.js";
import { Card, ErrorBox, Loading, PageHead, Stat } from "../components/Common.jsx";

const METRICS = [
  ["three_point_rate", "Three-point rate", (v) => `${(v * 100).toFixed(1)}%`],
  ["pace", "Pace (poss/48)", (v) => v.toFixed(1)],
  ["points_per_100", "Points per 100", (v) => v.toFixed(1)],
  ["avg_total_points", "Average total", (v) => v.toFixed(1)],
];

export default function Trends() {
  const [trends, setTrends] = useState(null);
  const [metric, setMetric] = useState("three_point_rate");
  const [projection, setProjection] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.trends().then(setTrends).catch(setError);
  }, []);

  useEffect(() => {
    let alive = true;
    setProjection(null);
    api
      .project(metric, 3)
      .then((p) => alive && setProjection(p))
      .catch((e) => alive && setError(e));
    return () => {
      alive = false;
    };
  }, [metric]);

  const fmt = METRICS.find(([k]) => k === metric)?.[2] ?? String;

  // The projected series is seeded with the final observed point so the dashed
  // line joins the solid one instead of floating off on its own.
  const chartData = projection
    ? [
        ...projection.observed.map((o, i, all) => ({
          season: o.season,
          actual: o.value,
          ...(i === all.length - 1
            ? { projected: o.value, lower: o.value, upper: o.value }
            : {}),
        })),
        ...projection.projected.map((p) => ({
          season: p.season,
          projected: p.value,
          lower: p.lower,
          upper: p.upper,
        })),
      ]
    : [];

  const latest = trends?.seasons?.[trends.seasons.length - 1];

  return (
    <>
      <PageHead title="League trends">
        Season-level pace and efficiency, computed from the box-score
        aggregates on every ingested game.
      </PageHead>

      <ErrorBox error={error} />

      {latest ? (
        <div className="grid" style={{ marginBottom: 18 }}>
          <Stat
            label="Latest season"
            value={latest.season}
            note={`${latest.games} games ingested`}
          />
          <Stat
            label="Three-point rate"
            value={`${(latest.three_point_rate * 100).toFixed(1)}%`}
            note={`${(latest.three_point_pct * 100).toFixed(1)}% accuracy`}
          />
          <Stat label="Pace" value={latest.pace.toFixed(1)} note="poss / 48 min" />
          <Stat
            label="Home win rate"
            value={`${(latest.home_win_rate * 100).toFixed(1)}%`}
          />
        </div>
      ) : null}

      <Card
        title="Trend and projection"
        sub="Linear extrapolation with a ±1.96 residual SE band"
      >
        <div className="row" style={{ marginBottom: 14 }}>
          {METRICS.map(([key, label]) => (
            <button
              key={key}
              className={metric === key ? "" : "ghost"}
              onClick={() => setMetric(key)}
            >
              {label}
            </button>
          ))}
        </div>

        {!projection ? (
          <Loading what="projection" />
        ) : projection.projected.length === 0 ? (
          <p className="muted">{projection.note}</p>
        ) : (
          <>
            <div style={{ width: "100%", height: 300 }}>
              <ResponsiveContainer>
                <LineChart
                  data={chartData}
                  margin={{ top: 6, right: 16, bottom: 6, left: -10 }}
                >
                  <CartesianGrid stroke="#262d3a" vertical={false} />
                  <XAxis dataKey="season" stroke="#8b95a7" fontSize={12} />
                  <YAxis
                    stroke="#8b95a7"
                    fontSize={12}
                    tickFormatter={fmt}
                    domain={["auto", "auto"]}
                  />
                  <Tooltip
                    formatter={(v) => (v == null ? "—" : fmt(v))}
                    contentStyle={{
                      background: "#141922",
                      border: "1px solid #262d3a",
                      borderRadius: 8,
                      fontSize: 13,
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="actual"
                    name="Observed"
                    stroke="#4c8dff"
                    strokeWidth={2.2}
                    dot={{ r: 3 }}
                    connectNulls
                    isAnimationActive={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="projected"
                    name="Projected"
                    stroke="#ff7a45"
                    strokeWidth={2}
                    strokeDasharray="5 4"
                    dot={{ r: 3 }}
                    isAnimationActive={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="upper"
                    name="Upper"
                    stroke="#ff7a45"
                    strokeWidth={1}
                    strokeOpacity={0.35}
                    dot={false}
                    isAnimationActive={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="lower"
                    name="Lower"
                    stroke="#ff7a45"
                    strokeWidth={1}
                    strokeOpacity={0.35}
                    dot={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <p className="muted" style={{ fontSize: 12.5, margin: "8px 0 0" }}>
              Slope {projection.slope_per_season} per season. {projection.note}
            </p>
          </>
        )}
      </Card>

      <Card title="By season">
        {!trends ? (
          <Loading what="trends" />
        ) : (
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>Season</th>
                  <th className="num">Games</th>
                  <th className="num">Pace</th>
                  <th className="num">Pts / 100</th>
                  <th className="num">3PA rate</th>
                  <th className="num">3P%</th>
                  <th className="num">Avg total</th>
                  <th className="num">Home win%</th>
                </tr>
              </thead>
              <tbody>
                {trends.seasons.map((s) => (
                  <tr key={s.season}>
                    <td>{s.season}</td>
                    <td className="num">{s.games}</td>
                    <td className="num">{s.pace.toFixed(1)}</td>
                    <td className="num">{s.points_per_100.toFixed(1)}</td>
                    <td className="num">
                      {(s.three_point_rate * 100).toFixed(1)}%
                    </td>
                    <td className="num">
                      {(s.three_point_pct * 100).toFixed(1)}%
                    </td>
                    <td className="num">{s.avg_total_points.toFixed(1)}</td>
                    <td className="num">
                      {(s.home_win_rate * 100).toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
