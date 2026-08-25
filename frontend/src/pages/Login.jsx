import { useState } from "react";
import { api, setToken } from "../lib/api.js";
import { ErrorBox } from "../components/Common.jsx";

export default function Login({ onSignedIn }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res =
        mode === "login"
          ? await api.login(email, password)
          : await api.register(email, password);
      setToken(res.access_token);
      onSignedIn(await api.me());
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
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
