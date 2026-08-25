import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { api } from "../lib/api.js";
import { Card, ErrorBox, Loading, PageHead, Stat } from "../components/Common.jsx";

const MODELS = ["blend", "brownian", "markov"];

export default function Calibration() {
  const [model, setModel] = useState("blend");
  const [report, setReport] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    setReport(null);
    api
      .backtest({ model, stride_seconds: 30, n_bins: 10 })
      .then((r) => alive && setReport(r))
      .catch((e) => alive && setError(e));
    return () => {
      alive = false;
    };
  }, [model]);

  useEffect(() => {
    api.compare(60).then(setComparison).catch(setError);
  }, []);

  const bins = (report?.overall.bins ?? []).filter((b) => b.count > 0);
  const diagonal = [
    { x: 0, y: 0 },
    { x: 1, y: 1 },
  ];

  return (
    <>
      <PageHead title="Model calibration">
        A win-probability model is calibrated when the moments it called 70%
        actually ended in a home win about 70% of the time. Points on the
        diagonal are perfectly calibrated; above the line means the model was
        too pessimistic, below means too confident.
      </PageHead>

      <ErrorBox error={error} />

      <Card title="Backtest" sub="Every game on a 30-second clock grid">
        <div className="row" style={{ marginBottom: 14 }}>
          {MODELS.map((m) => (
            <button
              key={m}
              className={model === m ? "" : "ghost"}
              onClick={() => setModel(m)}
            >
              {m}
            </button>
          ))}
        </div>

        {!report ? (
          <Loading what="backtest" />
        ) : (
          <>
            <div className="grid" style={{ marginBottom: 18 }}>
              <Stat
                label="Brier score"
                value={report.overall.brier.toFixed(4)}
                note="Lower is better · 0.25 = always 50%"
              />
              <Stat
                label="Brier skill"
                value={`${report.overall.brier_skill > 0 ? "+" : ""}${report.overall.brier_skill.toFixed(3)}`}
                note={`vs base rate ${(report.overall.base_rate * 100).toFixed(1)}%`}
              />
              <Stat
                label="Log loss"
                value={report.overall.log_loss.toFixed(4)}
              />
              <Stat
                label="Calibration error"
                value={report.overall.ece.toFixed(4)}
                note={`worst bin ${report.overall.mce.toFixed(3)}`}
              />
              <Stat
                label="Forecasts"
                value={report.overall.n.toLocaleString()}
                note={`${report.n_games} games`}
              />
            </div>

            <div style={{ width: "100%", height: 340 }}>
              <ResponsiveContainer>
                <ScatterChart margin={{ top: 6, right: 16, bottom: 16, left: -8 }}>
                  <CartesianGrid stroke="#262d3a" />
                  <XAxis
                    type="number"
                    dataKey="x"
                    domain={[0, 1]}
                    ticks={[0, 0.25, 0.5, 0.75, 1]}
                    tickFormatter={(v) => `${v * 100}%`}
                    stroke="#8b95a7"
                    fontSize={12}
                    label={{
                      value: "Predicted win probability",
                      position: "insideBottom",
                      offset: -8,
                      fill: "#8b95a7",
                      fontSize: 12,
                    }}
                  />
                  <YAxis
                    type="number"
                    dataKey="y"
                    domain={[0, 1]}
                    ticks={[0, 0.25, 0.5, 0.75, 1]}
                    tickFormatter={(v) => `${v * 100}%`}
                    stroke="#8b95a7"
                    fontSize={12}
                  />
                  <ZAxis type="number" dataKey="z" range={[40, 400]} />
                  <Tooltip
                    cursor={{ strokeDasharray: "3 3" }}
                    contentStyle={{
                      background: "#141922",
                      border: "1px solid #262d3a",
                      borderRadius: 8,
                      fontSize: 13,
                    }}
                    formatter={(v, name) =>
                      name === "z"
                        ? [v.toLocaleString(), "forecasts"]
                        : [`${(v * 100).toFixed(1)}%`, name === "x" ? "predicted" : "observed"]
                    }
                  />
                  <Scatter
                    name="Reliability"
                    data={bins.map((b) => ({
                      x: b.mean_predicted,
                      y: b.observed_rate,
                      z: b.count,
                    }))}
                    fill="#4c8dff"
                    isAnimationActive={false}
                  />
                  <Scatter
                    name="Perfect calibration"
                    data={diagonal}
                    line={{ stroke: "#4a5468", strokeDasharray: "4 4" }}
                    shape={() => null}
                    isAnimationActive={false}
                  />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
            <p className="muted" style={{ fontSize: 12.5, margin: "6px 0 0" }}>
              Bubble size is the number of forecasts in each bin. Fitted
              parameters: μ = {report.params.mu?.toFixed(2)}, σ ={" "}
              {report.params.sigma?.toFixed(2)} over {report.params.n_games}{" "}
              games.
            </p>
          </>
        )}
      </Card>

      {report ? (
        <Card
          title="Calibration by game state"
          sub="Where the model actually earns its keep"
        >
          <div style={{ width: "100%", height: 260 }}>
            <ResponsiveContainer>
              <LineChart
                data={Object.entries(report.by_time)
                  .filter(([, r]) => r.n > 0)
                  .map(([name, r]) => ({
                    name,
                    brier: r.brier,
                    skill: r.brier_skill,
                  }))}
                margin={{ top: 6, right: 16, bottom: 6, left: -14 }}
              >
                <CartesianGrid stroke="#262d3a" vertical={false} />
                <XAxis dataKey="name" stroke="#8b95a7" fontSize={11.5} />
                <YAxis stroke="#8b95a7" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    background: "#141922",
                    border: "1px solid #262d3a",
                    borderRadius: 8,
                    fontSize: 13,
                  }}
                  formatter={(v) => v.toFixed(4)}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line
                  dataKey="brier"
                  name="Brier score"
                  stroke="#4c8dff"
                  strokeWidth={2}
                  isAnimationActive={false}
                />
                <Line
                  dataKey="skill"
                  name="Brier skill"
                  stroke="#3fd39b"
                  strokeWidth={2}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="muted" style={{ fontSize: 12.5, margin: "6px 0 0" }}>
            The Brier score falls through the game because late forecasts are
            easier — a 20-point lead with two minutes left is not a hard call.
            Skill rising alongside it is the meaningful part: it says the model
            keeps beating the base rate by more as information accumulates.
          </p>
        </Card>
      ) : null}

      {comparison ? (
        <Card title="Model comparison" sub="Same games, same clock grid">
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>Model</th>
                  <th className="num">Brier</th>
                  <th className="num">Skill</th>
                  <th className="num">Log loss</th>
                  <th className="num">ECE</th>
                  <th className="num">Clutch Brier</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(comparison.models).map(([name, m]) => (
                  <tr key={name}>
                    <td>{name}</td>
                    <td className="num">{m.brier.toFixed(5)}</td>
                    <td className="num">
                      {m.brier_skill > 0 ? "+" : ""}
                      {m.brier_skill.toFixed(4)}
                    </td>
                    <td className="num">{m.log_loss.toFixed(5)}</td>
                    <td className="num">{m.ece.toFixed(4)}</td>
                    <td className="num">
                      {m.clutch?.brier != null ? m.clutch.brier.toFixed(5) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}
    </>
  );
}
