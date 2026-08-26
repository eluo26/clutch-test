# Deploying Clutch

The deployed app is **one container**: FastAPI serves the API *and* the built
React bundle from a single port. There is no separate frontend host, no CORS to
configure, and no reverse proxy to maintain.

```
                    ┌──────────────────────────────┐
   browser  ───────▶│  one container, one port     │
                    │                              │
                    │  /api/*   → FastAPI routers  │
                    │  /health  → health check     │
                    │  /assets/*→ hashed JS + CSS  │
                    │  everything else → index.html│
                    └──────────────────────────────┘
```

---

## Deploy to Render

### 1. Get the code on GitHub

```bash
cd clutch
gh repo create clutch --public --source=. --push
```

Render reads `render.yaml` from the repository root, so nothing else needs
configuring.

### 2. Create the service

1. Go to **[dashboard.render.com/blueprints](https://dashboard.render.com/blueprints)**
   → **New Blueprint Instance**.
2. Connect your GitHub account and pick the `clutch` repo.
3. Render reads `render.yaml` and shows one web service. Give the blueprint a
   name and click **Apply**.
4. It will prompt for `CLUTCH_ANTHROPIC_API_KEY`. **Leave it blank** unless you
   want the real text-to-SQL layer — see [below](#turning-on-real-text-to-sql).

First build takes 5–10 minutes: Node builds the bundle, then Python installs.
Later deploys are faster because Docker layers cache.

When it goes green you get a URL like `https://clutch-xxxx.onrender.com`.

### 3. Look around

Open the URL and click **Explore with the demo account**. The credentials are
in `render.yaml` (`demo@clutch.example` / `clutch-demo-2026`) and are printed on
the login page by design — it is a shared read-only account, so treat the
password as public and never reuse it.

---

## What the free tier actually gives you

Worth knowing before you put the link on a résumé.

**The service sleeps.** Free instances spin down after ~15 minutes with no
traffic. The next visitor waits **~50 seconds** for a cold start. That is a bad
first impression if a recruiter clicks the link cold. Two ways to handle it:

- Upgrade to the **Starter** plan (~$7/month), which never sleeps. Cheapest fix
  and the one I would pick if the link matters.
- Ping it every 10 minutes from an external cron (UptimeRobot, cron-job.org)
  hitting `/health`. Free, but Render considers it against the spirit of the
  free tier, and it burns your monthly instance hours.

**Storage is ephemeral.** Free instances get no persistent disk, so the SQLite
file lives in the container filesystem and is wiped on every deploy and every
restart. Consequences:

- Sample data comes back automatically — `CLUTCH_AUTO_SEED=true` reloads the
  100 bundled games at startup, which takes about two seconds.
- **Accounts do not survive.** Anyone who signs up loses the account on the next
  restart. The demo account is recreated at boot, so the demo path always works.
- Any real games you ingest are also lost.

For a portfolio demo this is fine and arguably ideal: the site is always in a
known-good state. To make it persistent, see below.

**512 MB RAM, shared CPU.** Comfortably enough. The Markov table is a few MB and
the whole sample database is under 30 MB.

---

## Making data persist

Two options, in increasing order of effort.

### A disk (simplest)

Render disks require a paid instance. Upgrade to Starter, then add to
`render.yaml`:

```yaml
    plan: starter
    disk:
      name: clutch-data
      mountPath: /data
      sizeGB: 1
```

The Dockerfile already points `CLUTCH_DATABASE_URL` at `/data/clutch.db`, so
this is the only change needed. Once mounted, keep `CLUTCH_AUTO_SEED=true` — it
is a no-op when the database already has games.

### Postgres (not recommended here)

`CLUTCH_DATABASE_URL` accepts a Postgres URL, and the ORM is portable. But the
**text-to-SQL layer would stop working**: its sandbox opens a second SQLite
handle in `mode=ro`, which has no Postgres equivalent
(`backend/app/nlq/guardrails.py` raises rather than silently running unsandboxed
SQL). On Postgres you would enforce read-only with a `SELECT`-only role and a
statement timeout instead. That is a real change, not a config flag.

---

## Turning on real text-to-SQL

Without a key, the query layer uses the deterministic rule-based provider — it
answers about six common questions and is honest about it in the UI. To use
Claude:

1. Get a key at [console.anthropic.com](https://console.anthropic.com).
2. In Render: your service → **Environment** → set `CLUTCH_ANTHROPIC_API_KEY`.
3. Save. Render redeploys automatically.

`/api/meta` reports which provider is live, and the Ask page labels every answer
with it, so you can confirm it took effect without digging through logs.

Cost is small — a couple of Sonnet calls per question — but it is *your* key on
a *public* page. The endpoint is behind authentication and rate-limited to 10
questions per minute per user (`CLUTCH_NLQ_RATE_LIMIT_PER_MINUTE`), but anyone
can create an account. If you publicise the link, consider lowering that limit
or setting a spend cap in the Anthropic console.

---

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `CLUTCH_SECRET_KEY` | — | **Required in production.** The app refuses to boot on the default. Render generates one. |
| `CLUTCH_ENV` | `dev` | `production` enables HSTS and the secret check. |
| `CLUTCH_DATABASE_URL` | `sqlite:///backend/clutch.db` | Container sets `sqlite:////data/clutch.db`. |
| `CLUTCH_AUTO_SEED` | `false` | Load bundled fixtures when the database has no games. |
| `CLUTCH_DEMO_EMAIL` / `CLUTCH_DEMO_PASSWORD` | unset | Both must be set. Advertised publicly on the login page. |
| `CLUTCH_FRONTEND_DIST` | `frontend/dist` | Serve the SPA from here. Ignored if there is no `index.html`. |
| `CLUTCH_ANTHROPIC_API_KEY` | unset | Falls back to the rule-based provider. |
| `CLUTCH_NLQ_RATE_LIMIT_PER_MINUTE` | `10` | Per user, in-process. |
| `CLUTCH_SIM_SERVICE_URL` | `http://127.0.0.1:8081` | The Java service. Unreachable is fine — Python takes over. |
| `CLUTCH_ACCESS_TOKEN_TTL_MINUTES` | `720` | |
| `PORT` | `8000` | Render sets this; the container honours it. |

---

## Running the container locally

Useful for reproducing a deploy problem without waiting on Render.

```bash
docker build -t clutch .

docker run --rm -p 8000:8000 \
  -e CLUTCH_SECRET_KEY=local-only-secret-please-change \
  -e CLUTCH_DEMO_EMAIL=demo@clutch.example \
  -e CLUTCH_DEMO_PASSWORD=clutch-demo-2026 \
  clutch
```

Then open <http://localhost:8000>. Add `-v clutch-data:/data` to keep the
database between runs.

---

## Troubleshooting

**Build fails at `npm ci`.** `frontend/package-lock.json` must be committed —
`npm ci` requires it and will not fall back to `npm install`. If you have been
editing dependencies, run `npm install` locally and commit the updated lock.

**Deploy succeeds, page is blank, console shows 404s for `/assets/...`.** The
frontend build stage produced nothing. Check the build log for the `npm run
build` step; usually a syntax error in a `.jsx` file that Vite reports but the
Docker layer does not make obvious.

**API calls return HTML instead of JSON.** Something is reaching the SPA
fallback that should have hit a router. The catch-all explicitly refuses `/api`,
`/health`, `/docs`, `/redoc`, and `/openapi.json` (`backend/app/spa.py`), so
this means the path is genuinely not registered — check for a typo against
`/docs`.

**"CLUTCH_SECRET_KEY must be set" on boot.** `CLUTCH_ENV=production` without a
real secret. Render's `generateValue: true` handles this; if you created the
service by hand, set the variable yourself.

**Login works, then every request 401s.** The instance restarted and the SQLite
file went with it, so the account no longer exists. Expected on the free tier —
see [Making data persist](#making-data-persist). The demo account is recreated
at boot, so it will still work.

**Old JavaScript keeps loading after a deploy.** Should not happen —
`index.html` is served `no-store` and asset filenames are content-hashed. If it
does, you are behind a CDN or proxy overriding cache headers.

**The site is slow on the first click.** Cold start from sleep. See
[the free tier](#what-the-free-tier-actually-gives-you).

---

## Deploying elsewhere

The `Dockerfile` is plain and has no Render-specific anything, so it runs on
Fly.io, Railway, Cloud Run, Azure Container Apps, or a VPS. The only two
requirements are:

- honour `PORT` (the container already does), and
- set `CLUTCH_SECRET_KEY`.

For a platform with a persistent volume, mount it at `/data` and drop
`CLUTCH_AUTO_SEED`, seeding once by hand instead:

```bash
docker exec <container> sh -c "cd /app/backend && python -m app.ingest.cli seed"
```
