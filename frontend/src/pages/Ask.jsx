import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { Card, ErrorBox, PageHead } from "../components/Common.jsx";

const SUGGESTIONS = [
  "How has three point rate changed by season?",
  "Who are the best clutch scorers?",
  "What is the home court win rate by season?",
  "How many overtime games were there?",
  "Which games were the closest?",
  "Who scored the most points?",
];

export default function Ask() {
  const [question, setQuestion] = useState(SUGGESTIONS[0]);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [tables, setTables] = useState([]);

  useEffect(() => {
    api
      .nlqSchema()
      .then((s) => setTables(s.tables))
      .catch(() => setTables([]));
  }, []);

  async function ask(q) {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.ask(q));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHead title="Ask the data">
        Questions are translated to SQL and run against the play-by-play
        database. The generated SQL is shown below every answer — it is
        validated as read-only and restricted to the analytics tables before it
        executes, so the query layer can never reach account data.
      </PageHead>

      <ErrorBox error={error} />

      <Card>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (question.trim().length >= 3) ask(question.trim());
          }}
        >
          <div className="row">
            <input
              style={{ flex: 1, minWidth: 260 }}
              value={question}
              maxLength={500}
              placeholder="Ask something about the play-by-play data…"
              onChange={(e) => setQuestion(e.target.value)}
            />
            <button type="submit" disabled={busy || question.trim().length < 3}>
              {busy ? "Thinking…" : "Ask"}
            </button>
          </div>
        </form>

        <div className="row" style={{ marginTop: 12, gap: 6 }}>
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              className="ghost"
              style={{ fontSize: 12.5, padding: "5px 10px" }}
              onClick={() => {
                setQuestion(s);
                ask(s);
              }}
            >
              {s}
            </button>
          ))}
        </div>

        {tables.length ? (
          <p className="muted" style={{ fontSize: 12.5, marginBottom: 0 }}>
            Queryable tables: {tables.map((t) => <code key={t} className="mono" style={{ marginRight: 8 }}>{t}</code>)}
          </p>
        ) : null}
      </Card>

      {result ? (
        <>
          {result.explanation ? (
            <Card title="Answer">
              <p style={{ margin: 0 }}>{result.explanation}</p>
            </Card>
          ) : null}

          <Card
            title="Results"
            sub={`${result.row_count} row${result.row_count === 1 ? "" : "s"}${
              result.truncated ? " (truncated)" : ""
            } · ${result.provider}`}
          >
            {result.rows.length === 0 ? (
              <p className="muted">No rows matched.</p>
            ) : (
              <div className="scroll-x">
                <table>
                  <thead>
                    <tr>
                      {result.columns.map((c) => (
                        <th key={c} className={c.match(/id$/) ? "" : "num"}>
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row, i) => (
                      <tr key={i}>
                        {row.map((cell, j) => (
                          <td
                            key={j}
                            className={typeof cell === "number" ? "num" : ""}
                          >
                            {cell === null ? (
                              <span className="muted">—</span>
                            ) : (
                              String(cell)
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="Generated SQL" sub="Validated read-only before execution">
            <pre className="sql">{result.sql}</pre>
          </Card>
        </>
      ) : null}
    </>
  );
}
