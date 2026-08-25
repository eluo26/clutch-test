import { useCallback, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, getToken, setToken } from "./lib/api.js";
import Login from "./pages/Login.jsx";
import Games from "./pages/Games.jsx";
import GameDetail from "./pages/GameDetail.jsx";
import Trends from "./pages/Trends.jsx";
import Ask from "./pages/Ask.jsx";
import Calibration from "./pages/Calibration.jsx";

export default function App() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(Boolean(getToken()));

  const signOut = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  // Resume an existing session on load, and drop it the moment any request
  // comes back 401 (expired token, revoked account, restarted backend).
  useEffect(() => {
    if (!getToken()) return;
    let alive = true;
    api
      .me()
      .then((u) => alive && setUser(u))
      .catch(() => alive && setToken(null))
      .finally(() => alive && setChecking(false));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    window.addEventListener("clutch:unauthorized", signOut);
    return () => window.removeEventListener("clutch:unauthorized", signOut);
  }, [signOut]);

  if (checking) {
    return (
      <div className="auth-wrap">
        <p className="muted">Restoring session…</p>
      </div>
    );
  }

  if (!user) return <Login onSignedIn={setUser} />;

  return (
    <div className="shell">
      <nav className="sidebar">
        <div>
          <h1 className="brand">
            Clu<span>tch</span>
          </h1>
          <p className="brand-sub">NBA win probability &amp; play-by-play</p>
        </div>
        <NavLink to="/games" className="nav-link">
          Games
        </NavLink>
        <NavLink to="/trends" className="nav-link">
          League trends
        </NavLink>
        <NavLink to="/ask" className="nav-link">
          Ask the data
        </NavLink>
        <NavLink to="/calibration" className="nav-link">
          Model calibration
        </NavLink>
        <div className="sidebar-foot">
          <div>{user.email}</div>
          <button
            className="ghost"
            style={{ marginTop: 8, width: "100%" }}
            onClick={signOut}
          >
            Sign out
          </button>
        </div>
      </nav>

      <main className="main">
        <Routes>
          <Route path="/games" element={<Games />} />
          <Route path="/games/:gameId" element={<GameDetail />} />
          <Route path="/trends" element={<Trends />} />
          <Route path="/ask" element={<Ask />} />
          <Route path="/calibration" element={<Calibration />} />
          <Route path="*" element={<Navigate to="/games" replace />} />
        </Routes>
      </main>
    </div>
  );
}
