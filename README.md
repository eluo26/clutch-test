# Clutch

A full-stack NBA analytics platform: ingest play-by-play and box-score data,
model in-game win probability two different ways, backtest the models honestly,
and query the whole play-by-play database in plain English.

```
┌──────────────┐   nba_api    ┌─────────────────────────────────────┐
│ stats.nba.com│─────────────▶│ ingest CLI  →  SQLite / Postgres     │
└──────────────┘              │   teams · games · plays · player_box │
                              └──────────────┬──────────────────────┘
                                             │
              ┌──────────────────────────────┼──────────────────────────┐
              │                              │                          │
     ┌────────▼─────────┐         ┌──────────▼──────────┐    ┌──────────▼─────────┐
     │ Brownian motion   │         │ Markov chain over   │    │ text-to-SQL layer  │
     │ with drift        │         │ possession states   │    │ (Claude + guard-   │
     │ (Stern 1994)      │         │ ── Java service ──▶ │    │  rails, read-only) │
     └────────┬─────────┘         └──────────┬──────────┘    └──────────┬─────────┘
              └──────────────┬───────────────┘                          │
                    ┌────────▼─────────┐                                │
                    │ FastAPI  :8000   │◀───────────────────────────────┘
                    │ JWT auth · CORS  │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │ React + Recharts │
                    │      :5173       │
                    └──────────────────┘
```

## Quick start

Nothing here needs the network, an API key, or a database server. The repo
ships 100 games of sample data.

```bash
git clone <your-repo-url> clutch && cd clutch

# 1. backend
cd backend
python -m pip install -e '.[dev]'
python -m app.ingest.cli seed          # loads the bundled sample games
python -m pytest                       # 165 tests, ~8s
python -m uvicorn app.main:app --reload --port 8000

# 2. frontend, in a second terminal
cd frontend && npm install && npm run dev
```

Open http://localhost:5173, create an account, and you are in. Or use the
Makefile: `make install && make seed && make api`, then `make web`.

Want a calibration report without leaving the terminal?

```bash
cd backend && python -m app.ingest.cli backtest --model blend
```

```
Model: blend   games: 100   forecasts: 9600
Fitted params: {'mu': 2.72, 'sigma': 15.64, 'possession_value': 0.55, 'n_games': 100}

  Brier        0.16345   (base rate 0.560)
  Brier skill  +0.3367
  Log loss     0.47899
  ECE / MCE    0.0330 / 0.0892

  Reliability diagram
  predicted   observed      n
      0.021     0.027   1012  #
      0.151     0.241    378  #########
      0.252     0.337    517  #############
      ...

  By game state
  Q1                     Brier 0.22993  skill +0.0668  n=2400
  Q4                     Brier 0.10159  skill +0.5877  n=1400
  Clutch (final 5:00)    Brier 0.05431  skill +0.7796  n=1000
```

## Loading real NBA data

The sample data is synthetic (see [Sample data](#sample-data)). For real games:

```bash
cd backend
python -m pip install -e '.[ingest]'
python -m app.ingest.cli nba --season 2023-24 --limit 50
```

`stats.nba.com` is rate-limited and unofficial. The ingest backs off and
retries, but pulling a full 1,230-game season takes roughly 40 minutes and will
occasionally get you temporarily blocked. Pull in chunks; the loader is
idempotent, so re-running is safe.

## The models

### Brownian motion with drift

Following Stern (1994), the home team's lead $X(t)$ is modelled as Brownian
motion with drift over $t \in [0, 1]$:

$$X(1) - X(t) \sim \mathcal{N}\big(\mu s,\; \sigma^2 s\big), \qquad s = 1 - t$$

$\mu$ is the expected full-game margin (home-court advantage) and $\sigma$ the
standard deviation of the final margin. Both are fit by maximum likelihood from
the ingested games rather than hard-coded — for a Brownian bridge the endpoint
is a sufficient statistic, so the MLE is just the sample mean and standard
deviation of observed final margins.

Two departures from the textbook form, both in `backend/app/winprob/brownian.py`:

- **Ties go to overtime.** The naive $P(X(1) > 0)$ silently hands the whole
  probability of an exact tie to the away team. The honest statement is
  $P(X(1) \ge 1) + \tfrac{1}{2}P(X(1) = 0)$, which with a half-point continuity
  correction collapses to the average of two shifted normal CDFs:

  $$P = \tfrac{1}{2}\left[\Phi\!\left(\tfrac{m - 0.5}{\sigma\sqrt{s}}\right) + \Phi\!\left(\tfrac{m + 0.5}{\sigma\sqrt{s}}\right)\right], \qquad m = d + \mu s$$

  This form is exactly symmetric under a sign flip when $\mu = 0$; the naive one
  is not, which is a fast way to catch the bug.

- **Possession value.** Holding the ball is worth real equity late and almost
  nothing early, so it enters as a points shift faded by $\sqrt{s}$.

### Markov chain over possession states

The diffusion approximation is fine in the second quarter and visibly wrong with
40 seconds left, where the game is discrete: a fixed number of trips remain,
each worth 0/1/2/3 points, and *who has the ball* dominates.

`backend/app/winprob/markov.py` models exactly that — an absorbing chain on
$(k, d, o)$ for $k$ trips remaining, home lead $d$, and team in possession $o$ —
solved by backward induction over $k$. Exact, no simulation error,
$O(k \cdot |d|)$.

One detail worth stating because it is easy to get backwards: $k$ counts
**trips**, not box-score possessions. An offensive rebound consumes a step and
leaves the ball with the same team. A game has roughly 200 possessions but ~220
trips, so the clock conversion uses 13.1 s/trip and the rate fitting divides by
$\text{FGA} + 0.44\,\text{FTA} + \text{TOV}$. Dividing by possessions instead
inflates every fitted rate ~10% and lands implied points-per-possession around
1.3 — a useful smoke test.

The chain reproduces the endgame asymmetries you would want it to: down 3 with
the ball beats down 4 by a mile, possession is worth ~53 points of win
probability when tied with one trip left and ~4 with a half to play.

### Blend

The default model is a cross-fade: pure diffusion above 6:00, pure chain at the
buzzer, linear in between. On the sample data all three land within 0.001 Brier
of each other overall, with the chain a touch better on calibration error — the
honest conclusion, and the reason all three are exposed side by side rather than
one being declared the winner.

## Calibration and backtesting

A win-probability model is calibrated when the moments it called 70% ended in a
home win about 70% of the time. `backend/app/winprob/calibration.py` reports:

| Metric | What it catches |
|---|---|
| **Brier score** | Overall squared error. 0.25 = always saying 50%. |
| **Brier skill** | Improvement over the base rate. Negative means worse than "home teams win 57%". |
| **Log loss** | The other proper scoring rule; punishes confident mistakes harder. |
| **ECE / MCE** | Mean and worst-case gap between predicted and observed frequency across reliability bins. |
| **By game state** | The same metrics sliced Q1 → clutch. |

Two decisions in the backtest that matter more than they look:

- **Forecasts are sampled on a fixed clock grid, not per event.** Events cluster
  around free throws and timeouts, so per-event sampling silently over-weights
  those moments.
- **Results are always reported sliced by time remaining.** A single Brier score
  across a whole game flatters any model, because garbage-time forecasts near 0
  and 1 are free. The clutch bucket is where a model earns its keep.

`GET /api/calibration/compare` runs all three models over the same games and the
same grid, so the numbers are actually comparable. The frontend draws the
reliability diagram with bubble size proportional to bin count.

## Natural-language query layer

`POST /api/nlq/query` takes an English question, sends the schema plus two
worked examples to Claude, and gets back one SQL statement.

The threat model is not a malicious user typing SQL — users only ever send
English. It is that the model can be *talked into* emitting whatever the
question implies, including `DROP TABLE users` or `SELECT password_hash`. So
generated SQL is treated as untrusted input and clears four independent gates
(`backend/app/nlq/guardrails.py`):

1. **Shape** — exactly one statement, starting with `SELECT` or `WITH`.
2. **Keyword deny-list** — no DDL/DML, no `PRAGMA`/`ATTACH`, no SQLite file
   functions, matched on whole words outside string literals.
3. **Table allow-list** — only `games`, `plays`, `teams`, `player_box`. The
   `users` table is not on it, so account data is unreachable by construction.
4. **Read-only connection** — execution happens on a *separate* SQLite handle
   opened `mode=ro`, with a row cap and a wall-clock interrupt. Even a complete
   bypass of gates 1–3 cannot write.

`tests/test_guardrails.py` is written as an attack list: stacked statements,
writes hidden in CTEs, `users` reached through a join and through a subquery,
`sqlite_master`, `readfile()`, `SELECT INTO OUTFILE`. `tests/test_api.py`
additionally swaps in a deliberately hostile provider that returns
`DROP TABLE users` and asserts the request is rejected and the table survives.

**Without an API key** the endpoint falls back to a deterministic rule-based
provider covering a handful of common questions, so the tests, CI, and a fresh
clone all work with no key and no network. Set `CLUTCH_ANTHROPIC_API_KEY` in
`.env` for the real thing.

## Authentication

- bcrypt (cost 12) via the `bcrypt` package directly — not `passlib`, which is
  unmaintained and breaks against bcrypt ≥ 4.1.
- Passwords ≥ 10 chars with letters and a digit; > 72 bytes is rejected rather
  than silently truncated, since bcrypt would otherwise treat two different long
  passwords as identical.
- HS256 JWTs with a typed claim and an expiry. The secret must be set explicitly
  when `CLUTCH_ENV=production` — the app refuses to boot on the default.
- Login is rate-limited per email address (not per IP, so one attacker cannot
  lock out every account from a shared address), compares against a dummy hash
  when the account does not exist, and floors the response at 150 ms — so
  "unknown account" and "wrong password" are indistinguishable in both content
  and timing.
- The frontend keeps its token in `sessionStorage`, not `localStorage`: it dies
  with the tab.
- Every analytics endpoint requires a bearer token; `tests/test_api.py`
  parametrises over the route list and asserts it, so a new unprotected route
  fails the suite.

## Java simulation service

`java-sim/` is a Spring Boot service on `:8081` owning the compute-heavy part of
the Markov work:

- `POST /api/sim/win-probability` — exact backward induction over the chain.
- `POST /api/sim/endgame` — Monte Carlo with a *deliberate-fouling policy* for
  the trailing team. That behaviour is a policy, not a transition matrix, so it
  is far easier to simulate than to solve — and 200k trials runs in ~130 ms in
  Java, which is the actual reason this service is not another Python function.
- `POST /api/sim/curve` — batch-score a whole game in one round trip.

```bash
cd java-sim && mvn spring-boot:run
```

It is **optional by design**. `backend/app/winprob/sim_client.py` falls back to
the pure-Python solver on any transport error, so the platform works fully
without a JVM. This is a speed dependency, never a correctness one — and
`MarkovSolverTest` asserts the two implementations agree.

## Sample data

`backend/data/sample/` holds 100 **synthetic** games across three seasons
(~500 KB gzipped). They are generated by `backend/app/ingest/synthetic.py`,
which simulates games possession by possession with team-specific efficiency and
pace, a shared game-level scoring environment, garbage-time convergence, and
overtime.

Why synthetic at all? Calibration needs volume. Reliability bins on the handful
of games you can politely pull from `stats.nba.com` in a minute are pure noise.
And the simulator is deliberately *not* either win-probability model — it works
in continuous clock time and emits real play-by-play rows — so scoring well
against it is a genuine test of the recursion rather than a tautology.

The output is checked against reality in `tests/test_ingest.py`:

| | synthetic | real NBA |
|---|---|---|
| Total points | 222 ± 20 | ~226 |
| Final margin | +2.9 ± 14.8 | ~+2.5 ± 14 |
| Possessions / team | 96 | ~99 |
| Three-point rate | 0.33 → 0.38 across seasons | rising |

Everything fabricated is labelled as such: seasons end in `S`, players are named
`BOS Guard 1`. It cannot be mistaken for real data. Team IDs *are* the real
`stats.nba.com` franchise ids, so synthetic and live games share a key space and
can sit in one database.

Regenerate deterministically with `make fixtures`.

## API

| Method | Path | |
|---|---|---|
| `POST` | `/api/auth/register` · `/login` | returns a bearer token |
| `GET` | `/api/auth/me` | |
| `GET` | `/api/games` | filter by `season`, `team` |
| `GET` | `/api/games/{id}/plays` | |
| `GET` | `/api/games/{id}/win-probability` | `?model=brownian\|markov\|blend` |
| `POST` | `/api/games/win-probability/state` | score any hypothetical game state |
| `GET` | `/api/trends/seasons` | pace, efficiency, 3PA rate by season |
| `GET` | `/api/trends/project` | OLS trend extrapolation with an error band |
| `POST` | `/api/nlq/query` | English → SQL → results |
| `GET` | `/api/nlq/schema` | what the model is told, and what is queryable |
| `POST` | `/api/calibration/backtest` | full reliability report |
| `GET` | `/api/calibration/compare` | all three models, same games |

Interactive docs at http://localhost:8000/docs.

## Layout

```
backend/
  app/
    winprob/     brownian.py · markov.py · calibration.py · service.py · sim_client.py
    nlq/         provider.py · guardrails.py · schema_context.py
    ingest/      nba_source.py · synthetic.py · loader.py · cli.py · schema.py
    routers/     auth.py · games.py · trends.py · nlq.py · calibration.py
    models.py  security.py  deps.py  config.py  db.py  main.py
  data/sample/   gzipped synthetic fixtures
  tests/         165 tests
java-sim/        Spring Boot: MarkovSolver · EndgameSimulator · SimController
frontend/        Vite + React + Recharts
```

## What is deliberately simple

Worth knowing before you extend it:

- **SQLite by default.** `CLUTCH_DATABASE_URL` accepts Postgres, but the
  sandboxed query runner is SQLite-specific — on Postgres you would enforce
  read-only with a `SELECT`-only role instead.
- **Rate limiting is in-process.** Fine for one worker; use Redis beyond that.
- **No refresh tokens.** Access tokens expire in 12 hours and you log in again.
- **Trend projection is a trend line, not a forecast.** It is OLS on season
  index with a residual-SE band, and the API response says so. Rule changes are
  what actually move these curves, and a linear fit knows nothing about them.
- **Team strength is not in the win-probability model.** Both models treat the
  two teams as equal apart from home court. A pre-game prior from ratings would
  be the single highest-value addition, and would show up immediately in the Q1
  Brier score — currently the weakest bucket at +0.07 skill.

## Licence

MIT.

## Further reading

- [`docs/MODELING.md`](docs/MODELING.md) — the derivations, the assumptions,
  the parity effect, the overtime boundary rule, and an honest list of what the
  models are still missing.
