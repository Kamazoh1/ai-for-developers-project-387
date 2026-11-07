# syntax=docker/dockerfile:1
#
# One image for the whole app: the API and the built frontend, served by one process.
#   docker build -t call-calendar .
#   docker run --rm -e PORT=8080 -p 8080:8080 call-calendar
#
# The app listens on $PORT (Render sets it; the default 10000 is only a fallback).

# Versions follow mise.toml (node 26, python 3.13, uv 0.13.6).
ARG NODE_VERSION=26
ARG PYTHON_VERSION=3.13
ARG UV_VERSION=0.13.6

# --- 1. contract -> SDK -> frontend build -----------------------------------------------------
FROM node:${NODE_VERSION}-slim AS frontend
WORKDIR /src

# Dependencies first, so that code changes do not reinstall them.
COPY api/package.json api/package-lock.json api/
RUN npm ci --prefix api
COPY frontend/package.json frontend/package-lock.json frontend/
RUN npm ci --prefix frontend

COPY api api
COPY frontend frontend
# Same steps as `mise run generate` + `mise run build`: TypeSpec -> OpenAPI -> SDK, then Vite.
# The frontend calls the API on the same origin, so VITE_API_URL stays empty.
RUN npm run build --prefix api \
 && npm run generate --prefix frontend \
 && npm run build --prefix frontend

# --- 2. backend dependencies (locked, no dev tools) --------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS backend-deps
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/
RUN uv sync --project backend --locked --no-dev --no-install-project

# --- 3. runtime ----------------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime
RUN useradd --system --uid 10001 --create-home app
WORKDIR /app/backend

COPY --from=backend-deps /app/backend/.venv /app/backend/.venv
COPY backend/app ./app
COPY --from=frontend /src/frontend/dist /app/static

ENV PATH="/app/backend/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    STATIC_DIR=/app/static \
    PORT=10000 \
    # The data lives in the container: it is gone after a restart or redeploy.
    # Mount a volume and point DATABASE_PATH at it to keep it.
    DATABASE_PATH=/tmp/call-calendar.db

USER app
EXPOSE 10000

# `sh -c` on purpose: ${PORT} is read when the container starts, not when it is built.
# `exec` makes uvicorn PID 1, so it gets SIGTERM and shuts down cleanly.
CMD ["sh", "-c", "exec uvicorn --factory app.main:create_app --host 0.0.0.0 --port \"${PORT}\""]
