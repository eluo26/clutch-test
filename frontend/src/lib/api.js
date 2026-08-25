/**
 * Thin fetch wrapper.
 *
 * The access token is held in memory and mirrored into sessionStorage so a
 * page refresh does not log you out. sessionStorage rather than localStorage
 * is deliberate: the token dies with the tab, which is the right default for
 * a bearer token that a script on the page can read.
 */

const TOKEN_KEY = "clutch.token";

let token = null;
try {
  token = sessionStorage.getItem(TOKEN_KEY);
} catch {
  token = null;
}

export function getToken() {
  return token;
}

export function setToken(next) {
  token = next;
  try {
    if (next) sessionStorage.setItem(TOKEN_KEY, next);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode; in-memory only */
  }
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, { method = "GET", body, signal } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(path, {
    method,
    headers,
    signal,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (res.status === 401) {
    setToken(null);
    window.dispatchEvent(new Event("clutch:unauthorized"));
  }

  const text = await res.text();
  const data = text ? JSON.parse(text) : null;

  if (!res.ok) {
    const detail =
      typeof data?.detail === "string"
        ? data.detail
        : Array.isArray(data?.detail)
          ? data.detail.map((d) => d.msg).join("; ")
          : `Request failed (${res.status})`;
    throw new ApiError(res.status, detail);
  }
  return data;
}

export const api = {
  register: (email, password) =>
    request("/api/auth/register", { method: "POST", body: { email, password } }),
  login: (email, password) =>
    request("/api/auth/login", { method: "POST", body: { email, password } }),
  me: () => request("/api/auth/me"),

  games: (params = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== "" && v != null),
    );
    return request(`/api/games?${qs}`);
  },
  winProbability: (gameId, model = "blend") =>
    request(`/api/games/${gameId}/win-probability?model=${model}`),
  scoreState: (payload) =>
    request("/api/games/win-probability/state", { method: "POST", body: payload }),

  trends: () => request("/api/trends/seasons"),
  project: (metric, horizon = 3) =>
    request(`/api/trends/project?metric=${metric}&horizon=${horizon}`),

  ask: (question) =>
    request("/api/nlq/query", { method: "POST", body: { question, explain: true } }),
  nlqSchema: () => request("/api/nlq/schema"),

  backtest: (payload) =>
    request("/api/calibration/backtest", { method: "POST", body: payload }),
  compare: (stride = 30) =>
    request(`/api/calibration/compare?stride_seconds=${stride}`),
};
