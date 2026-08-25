export function PageHead({ title, children }) {
  return (
    <div className="page-head">
      <h1>{title}</h1>
      {children ? <p>{children}</p> : null}
    </div>
  );
}

export function Card({ title, sub, children }) {
  return (
    <section className="card">
      {title ? (
        <h2>
          {title}
          {sub ? <span className="sub">{sub}</span> : null}
        </h2>
      ) : null}
      {children}
    </section>
  );
}

export function Stat({ label, value, note }) {
  return (
    <div className="stat">
      <div className="k">{label}</div>
      <div className="v">{value}</div>
      {note ? <div className="note">{note}</div> : null}
    </div>
  );
}

export function ErrorBox({ error }) {
  if (!error) return null;
  return <div className="error">{error.detail || error.message}</div>;
}

export function Loading({ what = "data" }) {
  return <p className="muted">Loading {what}…</p>;
}

export function Empty({ children }) {
  return <p className="muted">{children}</p>;
}

/**
 * Seconds-left-in-regulation to a readable clock.
 *
 * Negative values are overtime — see the backend's app/winprob/clock.py for
 * why a boundary value like 0 or -300 is ambiguous (end of a period, or the
 * tip of the next one) and why the score is what disambiguates it. Here we
 * only need a label, so boundaries read as "End Q4" / "End OT1".
 */
export function formatGameClock(secondsRemaining) {
  if (secondsRemaining <= 0) {
    const elapsed = -secondsRemaining;
    if (elapsed % 300 === 0) {
      return elapsed === 0 ? "End Q4" : `End OT${elapsed / 300}`;
    }
    const ot = Math.floor(elapsed / 300) + 1;
    const within = 300 - (elapsed % 300);
    return `OT${ot} ${Math.floor(within / 60)}:${String(
      Math.floor(within % 60),
    ).padStart(2, "0")}`;
  }
  const period = 4 - Math.floor(secondsRemaining / 720);
  const within = secondsRemaining % 720;
  return `Q${Math.min(4, period)} ${Math.floor(within / 60)}:${String(
    Math.floor(within % 60),
  ).padStart(2, "0")}`;
}

/** Axis tick label for elapsed game seconds (0 at tip-off, > 2880 in overtime). */
export function periodLabel(elapsedSeconds) {
  if (elapsedSeconds < 2880) return `Q${Math.floor(elapsedSeconds / 720) + 1}`;
  return `OT${Math.floor((elapsedSeconds - 2880) / 300) + 1}`;
}

export const pct = (x, digits = 1) => `${(x * 100).toFixed(digits)}%`;
