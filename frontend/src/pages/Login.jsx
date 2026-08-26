import { useEffect, useState } from "react";
import { api, setToken } from "../lib/api.js";
import { ErrorBox } from "../components/Common.jsx";

export default function Login({ onSignedIn }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [demo, setDemo] = useState(null);

  // Deployments can advertise a shared read-only account so a visitor can look
  // around without signing up. Locally there is none and this stays hidden.
  useEffect(() => {
    let alive = true;
    api
      .meta()
      .then((m) => alive && setDemo(m.demo))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  async function signIn(nextEmail, nextPassword, register = false) {
    setError(null);
    setBusy(true);
    try {
      const res = register
        ? await api.register(nextEmail, nextPassword)
        : await api.login(nextEmail, nextPassword);
      setToken(res.access_token);
      onSignedIn(await api.me());
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  function submit(e) {
    e.preventDefault();
    signIn(email, password, mode === "register");
  }

  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <h1>
          Clu<span style={{ color: "var(--accent)" }}>tch</span>
        </h1>
        <p className="tagline">
          In-game win probability, league trends, and a play-by-play database
          you can ask questions in plain English.
        </p>

        <ErrorBox error={error} />

        <form onSubmit={submit}>
          <label className="field">
            Email
            <input
              type="email"
              value={email}
              autoComplete="username"
              required
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label className="field">
            Password
            <input
              type="password"
              value={password}
              autoComplete={
                mode === "login" ? "current-password" : "new-password"
              }
              required
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {mode === "register" ? (
            <p className="muted" style={{ fontSize: 12, margin: 0 }}>
              At least 10 characters, with letters and a digit.
            </p>
          ) : null}
          <button type="submit" disabled={busy}>
            {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>

        {demo ? (
          <>
            <div className="auth-divider">
              <span>or</span>
            </div>
            <button
              className="ghost"
              style={{ width: "100%" }}
              disabled={busy}
              onClick={() => signIn(demo.email, demo.password)}
            >
              Explore with the demo account
            </button>
            <p
              className="muted"
              style={{ fontSize: 11.5, textAlign: "center", margin: "8px 0 0" }}
            >
              Shared and read-only. Anything you save here is visible to
              everyone else using it.
            </p>
          </>
        ) : null}

        <div className="auth-toggle">
          {mode === "login" ? "No account yet?" : "Already have an account?"}{" "}
          <button
            onClick={() => {
              setMode(mode === "login" ? "register" : "login");
              setError(null);
            }}
          >
            {mode === "login" ? "Create one" : "Sign in"}
          </button>
        </div>
      </div>
    </div>
  );
}
