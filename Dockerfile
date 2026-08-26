# Single container: FastAPI serves both the API and the built React bundle,
# so the whole app is one process on one port and there is no CORS to
# configure in production.

# ---------------------------------------------------------------------------
# Stage 1 — build the frontend
# ---------------------------------------------------------------------------
FROM node:20-slim AS web

WORKDIR /web

# package*.json first so `npm ci` is cached until dependencies actually change.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# ---------------------------------------------------------------------------
# Stage 2 — runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies before source, again for layer caching. Only pyproject is
# needed to resolve them.
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app/__init__.py backend/app/__init__.py
RUN python -m pip install --upgrade pip \
    && python -m pip install -e './backend[llm]'

COPY backend/ backend/
COPY --from=web /web/dist/ frontend/dist/

# Run as an unprivileged user. The database lives under /data so a mounted
# volume (or a Render disk) can persist it without touching the code tree.
RUN useradd --create-home --uid 10001 clutch \
    && mkdir -p /data \
    && chown -R clutch:clutch /data /app
USER clutch

ENV CLUTCH_ENV=production \
    CLUTCH_DATABASE_URL=sqlite:////data/clutch.db \
    CLUTCH_FRONTEND_DIST=/app/frontend/dist \
    CLUTCH_AUTO_SEED=true \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT','8000')}/health\").read()"

# Shell form so $PORT is expanded — hosts assign it at runtime.
CMD python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --app-dir backend
