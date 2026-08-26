"""Serve the built React bundle from FastAPI.

In development Vite serves the UI on :5173 and proxies ``/api`` to :8000, so
none of this runs. In the deployed container there is one process on one port:
the API answers ``/api/*``, and everything else falls through to the SPA.

Two details that are easy to get wrong:

* **The catch-all must not swallow the API.** It is mounted last and explicitly
  refuses the API prefixes, so a typo'd endpoint returns a JSON 404 from
  FastAPI rather than a 200 of ``index.html`` -- which would otherwise show up
  as the baffling "why is my fetch returning HTML" bug.
* **Hashed assets versus index.html.** Vite fingerprints filenames under
  ``/assets``, so those are immutable and cached hard. ``index.html`` names the
  current bundle and must never be cached, or a browser will keep loading the
  previous deploy's JavaScript forever.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

log = logging.getLogger(__name__)

# Paths owned by the API. A request starting with any of these never reaches
# the SPA fallback.
API_PREFIXES = ("/api", "/health", "/docs", "/redoc", "/openapi.json")

IMMUTABLE = "public, max-age=31536000, immutable"
NO_STORE = "no-cache, no-store, must-revalidate"


class _HashedAssets(StaticFiles):
    """Vite's /assets output, served with a long cache lifetime."""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = IMMUTABLE
        return response


def mount(app: FastAPI, dist: Path) -> None:
    """Attach the SPA. Call after every router is registered."""
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", _HashedAssets(directory=assets), name="assets")

    index = dist / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(request: Request, full_path: str):
        path = "/" + full_path
        if any(path == p or path.startswith(p + "/") for p in API_PREFIXES):
            raise HTTPException(status_code=404, detail="Not found")

        # Serve a real file when one exists (favicon, robots.txt, and so on),
        # resolving it first so that "../" cannot escape the bundle.
        if full_path:
            candidate = (dist / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(dist.resolve()):
                return FileResponse(candidate)

        del request
        return FileResponse(index, headers={"Cache-Control": NO_STORE})

    log.info("serving frontend bundle from %s", dist)
