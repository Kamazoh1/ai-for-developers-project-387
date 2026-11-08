# Call Calendar

Booking service for calls. Contract-first: TypeSpec -> OpenAPI -> generated frontend SDK.

## Commands

All tooling versions are pinned in `mise.toml`; run everything through mise.

- `mise run install` — install all dependencies
- `mise run hooks` — install git hooks (pre-commit runs `mise run precommit`: lint + types)
- `mise run verify` — **the one command for everything**: `check` + the browser scenario `e2e`. Same locally and in CI (CI runs exactly this). Needs `mise run e2e:install` once
- `mise run check` — fast part of `verify`: lint + types + tests + build (the pre-commit hook runs a subset of it)
- `mise run test` — pytest + vitest; regenerates the contract first, since `backend/tests/test_contract.py` checks real responses against `api/dist/openapi.yaml`
- `mise run e2e` — browser scenario (Playwright) on a real backend and frontend, without mocked API; part of `verify`, needs `mise run e2e:install` once
- `mise run docker:build` / `docker:run` — build / run the Docker image (API + built frontend in one process, listens on `$PORT`); `mise run docker:smoke` builds it, starts it on a free `PORT` and runs the browser scenario against it (own CI job `image`); needs Docker and `e2e:install`
- `mise run e2e:url -- <url>` — the same browser scenario against a running app (the container, the public Render URL)
- `mise run fix` — auto-fix lint and formatting
- `mise run generate` — rebuild OpenAPI and the frontend SDK after editing `api/main.tsp`
- `mise daemons start|stop|status|logs` — dev servers: backend :8000, frontend :5173

## Layout

- `api/` — TypeSpec contract (`main.tsp`), emits `api/dist/openapi.yaml`
- `backend/` — FastAPI (Python 3.13, uv). App in `backend/app`, tests in `backend/tests`
  The app is built by the factory `app.main:create_app` (no module-level `app`, so importing has no side effects); start it with `uvicorn --factory app.main:create_app`
- `.github/scripts/` — Python helpers of the agent workflows (review limit, browser check): standard library only, linted with `backend`, tested in `backend/tests` (`test_review_limit.py`, `test_browser_check.py`)
- `frontend/` — Vite + React + TypeScript + Mantine. `frontend/src/api` is generated, never edit it

## Rules

- Commits follow Conventional Commits (`feat:`, `fix:`, `chore:`, ...); the `commit-msg` hook enforces it.
- A commit that implements a ticket references the ticket it closes, e.g. `feat: book a free slot (#18)`. GitHub turns the number into a link, so the history shows which commit did which task.
- The API contract in `api/main.tsp` is the source of truth; change it first, then implement the backend to match.
- Never commit keys, tokens or other secrets. The Render API key comes from the `RENDER_API_KEY` environment variable (`.mcp.json` only references it); `.env*` is git-ignored.
- Do not edit or delete `.github/workflows/hexlet-check.yml`.
- Keep `mise run check` green before committing.

## Agent skills

### Issue tracker

Issues live in GitHub Issues (`Kamazoh1/ai-for-developers-project-387`, via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
