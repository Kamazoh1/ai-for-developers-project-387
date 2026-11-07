"""Serve the built frontend from the API process (the container image, #32).

Registered last, so every real route (``/health``, ``/api/...``) wins. Anything else is a file of
the build, or, for a client-side route like ``/book/intro-call``, the index page so that a reload
works. A path that looks like a file but is missing is a plain 404, not the index page; an unknown
``/api/...`` path stays a JSON 404.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

NO_CACHE = {"Cache-Control": "no-cache"}
# Vite puts a content hash in the names under ``assets/``, so they never change.
IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}


def install_frontend(app: FastAPI, root: Path) -> None:
    root = root.resolve()
    index = root / "index.html"

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)

        if path:
            candidate = (root / path).resolve()
            if candidate.is_file() and candidate.is_relative_to(root):
                headers = IMMUTABLE if candidate.parent.name == "assets" else NO_CACHE
                return FileResponse(candidate, headers=headers)
            if Path(path).suffix:
                raise HTTPException(status_code=404)

        return FileResponse(index, headers=NO_CACHE)
